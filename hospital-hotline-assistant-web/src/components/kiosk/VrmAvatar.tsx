import { useEffect, useRef, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import type { VoiceCallState } from '../../hooks/useVoiceCall';
import { NurseAvatar } from './NurseAvatar';

type AvatarPose = 'idle' | 'listening' | 'thinking' | 'speaking';

interface VrmAvatarProps {
  state: VoiceCallState | 'idle';
  /** Live loudness of the assistant's voice (0..1) — drives the mouth
   *  blendshape while speaking. Must be identity-stable per render
   *  (useVoiceCall.getOutputLevel). */
  getLevel?: () => number;
  /** Loudness + spectral centroid — enables vowel-shaped (A/I/U/E/O)
   *  lip sync (useVoiceCall.getOutputFeatures). Falls back to getLevel
   *  (openness-only `aa`) when absent. */
  getFeatures?: () => { level: number; centroid: number };
}

function toPose(state: VoiceCallState | 'idle'): AvatarPose {
  switch (state) {
    case 'listening':
      return 'listening';
    case 'speaking':
      return 'speaking';
    case 'thinking':
    case 'uploading':
    case 'starting':
    case 'greeting':
      return 'thinking';
    default:
      return 'idle';
  }
}

const MODEL_URL = '/avatar/nurse.vrm';

// ── Pose targets ─────────────────────────────────────────────────────────
// Euler XYZ (radians) per normalized humanoid bone. The normalized rig is
// guaranteed T-pose at rest regardless of how the model was authored, so
// these numbers work for any VRM. Framing is chest-up, so hands mostly sit
// below the frame — poses are about head/neck/shoulder language.
type BoneKey =
  | 'hips'
  | 'spine'
  | 'chest'
  | 'neck'
  | 'head'
  | 'leftShoulder'
  | 'leftUpperArm'
  | 'leftLowerArm'
  | 'leftHand'
  | 'rightShoulder'
  | 'rightUpperArm'
  | 'rightLowerArm'
  | 'rightHand';

type Vec3 = readonly [number, number, number];
type PoseTargets = Partial<Record<BoneKey, Vec3>>;

// Relaxed arms shared by every pose — hanging nearly straight so the
// hands stay below the chest-up frame.
const ARMS_RELAXED: PoseTargets = {
  leftShoulder: [0, 0, -0.05],
  leftUpperArm: [0.15, 0.05, -1.14],
  leftLowerArm: [0.02, 0.25, -0.08],
  leftHand: [0, 0.1, -0.1],
  rightShoulder: [0, 0, 0.05],
  rightUpperArm: [0.15, -0.05, 1.14],
  rightLowerArm: [0.02, -0.25, 0.08],
  rightHand: [0, -0.1, 0.1],
};

const POSES: Record<AvatarPose, PoseTargets> = {
  idle: {
    ...ARMS_RELAXED,
    spine: [0.02, 0, 0],
    neck: [0.02, 0, 0],
    head: [0.01, 0, 0],
  },
  // Base listening = the "attentive" phase; jot/reassure override below.
  listening: {
    ...ARMS_RELAXED,
    spine: [0.03, 0, 0],
    neck: [0.05, 0.05, 0.02],
    head: [0.07, 0.1, 0.06],
  },
  thinking: {
    ...ARMS_RELAXED,
    spine: [0.02, 0, 0],
    neck: [-0.06, -0.08, -0.02],
    head: [-0.12, -0.14, -0.08],
    rightShoulder: [0, 0, 0.1],
    // Upper/lower arm serve only as the IK fallback + slerp seed; the
    // raised arm itself is solved by the 2-bone IK in the tick loop.
    rightUpperArm: [0.75, 0.05, 1.2],
    rightLowerArm: [0, -2.15, 0],
    // Relaxed inward curl so the hand doesn't read as a flat open palm.
    rightHand: [0.35, -0.25, -0.3],
  },
  speaking: {
    ...ARMS_RELAXED,
    spine: [0.02, 0, 0],
    neck: [0.01, 0, 0],
    head: [0.02, 0, 0],
  },
};

// ── Listening behavior loop ──────────────────────────────────────────────
// attentive: eyes on the patient, soft smile, slow affirming nods.
// jot (after the patient has talked a while): glance down + tiny writing
//   motion — the hands are below the frame, so head + shoulder sell it.
// reassure (right after jotting): back up to the patient with a sweet
//   smile, then attentive again.
type ListenPhase = 'attentive' | 'jot' | 'reassure';

const LISTEN_OVERRIDES: Record<ListenPhase, PoseTargets> = {
  attentive: {},
  jot: {
    neck: [0.22, 0.03, 0],
    head: [0.32, 0.06, 0.02],
    rightShoulder: [0, 0, 0.12],
    // Arm barely lifts — the writing happens fully below the frame; the
    // bowed head, downcast eyes and shoulder tremor tell the story.
    rightUpperArm: [0.3, -0.05, 1.1],
    rightLowerArm: [0, -0.5, 0.1],
    rightHand: [0.2, -0.2, 0],
  },
  reassure: {
    neck: [0, 0.05, 0.02],
    head: [-0.02, 0.09, 0.05],
  },
};

const JOT_AFTER_MIN = 5.5; // s of continuous listening before she jots
const JOT_AFTER_VAR = 2.5;
const JOT_LEN_MIN = 2.4; // s spent jotting
const JOT_LEN_VAR = 1.0;
const REASSURE_LEN = 1.7; // s of sweet smile before returning

const BONE_KEYS: BoneKey[] = [
  'hips',
  'spine',
  'chest',
  'neck',
  'head',
  'leftShoulder',
  'leftUpperArm',
  'leftLowerArm',
  'leftHand',
  'rightShoulder',
  'rightUpperArm',
  'rightLowerArm',
  'rightHand',
];
const ZERO: Vec3 = [0, 0, 0];

// Where she looks, expressed as an offset from the head in world space
// (x right, y up, z toward the camera). On the patient almost always;
// down while jotting, up-left while thinking.
const LOOK_OFFSETS: Record<AvatarPose | 'jot', Vec3> = {
  idle: [0, -0.05, 1.4],
  listening: [0.05, -0.06, 1.3],
  jot: [0.1, -0.6, 0.7],
  thinking: [-0.4, 0.45, 1.1],
  speaking: [0, -0.02, 1.4],
};

// VRM vowel visemes as overlapping triangular bands over the normalized
// spectral centroid: rounded う/お live low, open あ mid, wide え/い high.
// [expression, band center, band half-width]
const VOWEL_BANDS: Array<[name: 'ou' | 'oh' | 'aa' | 'ee' | 'ih', center: number, width: number]> = [
  ['ou', 0.1, 0.22],
  ['oh', 0.3, 0.2],
  ['aa', 0.5, 0.2],
  ['ee', 0.68, 0.18],
  ['ih', 0.88, 0.24],
];
// Dev pin (?vowel=aa …) → representative centroid per vowel.
const VOWEL_CENTROIDS: Record<string, number> = { ou: 0.1, oh: 0.3, aa: 0.5, ee: 0.68, ih: 0.88 };

// Warmth of her smile per situation (smoothed `happy` expression weight).
const HAPPY_TARGETS: Record<AvatarPose, number> = {
  idle: 0.15,
  listening: 0.25,
  thinking: 0.05,
  speaking: 0.2,
};

/**
 * 3D VRM avatar for the kiosk. Loads /avatar/nurse.vrm (a VRoid-authored
 * model) and animates it entirely procedurally, framed chest-up so the
 * face carries the performance. Listening runs a behavior loop: attentive
 * (eyes on the patient, soft smile, slow affirming nods) → after the
 * patient has talked a while, a glance down with a tiny below-frame
 * writing motion → back up with a sweet smile, repeating for long
 * utterances. Thinking is pen-to-chin-style hand-near-face with eyes up;
 * speaking lip-syncs the live TTS loudness onto the `aa` expression.
 * Breathing, randomized blinks and smooth expression cross-fades run
 * throughout. Falls back to the 2D <NurseAvatar/> whenever the model or
 * WebGL fails, so the tile is never empty.
 */
export function VrmAvatar({ state, getLevel, getFeatures }: VrmAvatarProps) {
  const reduce = useReducedMotion();
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);

  const poseRef = useRef<AvatarPose>('idle');
  poseRef.current = toPose(state);
  const getLevelRef = useRef(getLevel);
  getLevelRef.current = getLevel;
  const getFeaturesRef = useRef(getFeatures);
  getFeaturesRef.current = getFeatures;
  const reduceRef = useRef(!!reduce);
  reduceRef.current = !!reduce;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let dispose: (() => void) | null = null;

    (async () => {
      try {
        const THREE = await import('three');
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js');
        const { VRMLoaderPlugin, VRMUtils } = await import('@pixiv/three-vrm');

        const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.outputColorSpace = THREE.SRGBColorSpace;

        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(26, 3 / 4, 0.1, 20);

        scene.add(new THREE.AmbientLight(0xffffff, 0.9));
        const key = new THREE.DirectionalLight(0xffffff, 1.15);
        key.position.set(0.4, 1.2, 1.5);
        scene.add(key);

        const loader = new GLTFLoader();
        loader.register((parser) => new VRMLoaderPlugin(parser));
        const gltf = await loader.loadAsync(MODEL_URL);
        const vrm = gltf.userData.vrm;
        if (!vrm) throw new Error('not a VRM');
        if (disposed) {
          VRMUtils.deepDispose(vrm.scene);
          renderer.dispose();
          return;
        }
        VRMUtils.rotateVRM0(vrm); // VRM0 models face the other way; no-op for VRM1
        vrm.scene.traverse((obj: { frustumCulled?: boolean }) => {
          obj.frustumCulled = false;
        });
        scene.add(vrm.scene);

        // ── Camera framing: waist-up portrait based on the model's own head height
        vrm.scene.updateMatrixWorld(true);
        const headRaw = vrm.humanoid?.getRawBoneNode?.('head');
        const headPos = new THREE.Vector3(0, 1.35, 0);
        headRaw?.getWorldPosition(headPos);
        const hipsRaw = vrm.humanoid?.getRawBoneNode?.('hips');
        const hipsPos = new THREE.Vector3(0, 0.8, 0);
        hipsRaw?.getWorldPosition(hipsPos);
        // All framing/prop offsets are proportional to the model's own
        // head-to-hips distance, so differently sized/scaled VRoid exports
        // frame themselves (v1 ≈ 0.55m torso was the reference).
        const torso = Math.max(headPos.y - hipsPos.y, 0.2);
        const propScale = torso / 0.55;
        // Chest-up close framing: from the very top of the model (hair,
        // cap and all — chibi proportions make head-relative guesses crop
        // the crown) down to just below the chest bone. Face large,
        // shoulders in frame for nod/jot body language, hands below frame.
        const bbox = new THREE.Box3().setFromObject(vrm.scene);
        const chestRaw = vrm.humanoid?.getRawBoneNode?.('chest') ?? hipsRaw;
        const chestPos = new THREE.Vector3(0, hipsPos.y + 0.4 * torso, 0);
        chestRaw?.getWorldPosition(chestPos);
        const topY = bbox.max.y + 0.01 * (bbox.max.y - hipsPos.y);
        // Mid-chest crop — below-frame limbs (e.g. the jot writing arm)
        // can never poke into the shot at odd angles.
        const bottomY = chestPos.y + 0.14 * torso;
        const centerY = (topY + bottomY) / 2;
        const dist = (topY - centerY) / Math.tan(((camera.fov / 2) * Math.PI) / 180);
        camera.position.set(0, centerY, dist);
        camera.lookAt(0, centerY, 0);

        // ── Right-arm 2-bone IK geometry (rest pose, world space) ───────
        // Euler guessing kept folding the raised arm behind the body; the
        // IK solver instead places the wrist at an explicit point in front
        // of the chin with the elbow pulled toward a forward-down pole, so
        // the arm can only fold in front of the torso.
        const ikGeom = (() => {
          const ua = vrm.humanoid?.getRawBoneNode?.('rightUpperArm');
          const la = vrm.humanoid?.getRawBoneNode?.('rightLowerArm');
          const ha = vrm.humanoid?.getRawBoneNode?.('rightHand');
          const nua = vrm.humanoid?.getNormalizedBoneNode?.('rightUpperArm');
          const nla = vrm.humanoid?.getNormalizedBoneNode?.('rightLowerArm');
          if (!ua || !la || !ha || !nua || !nla) return null;
          const s = new THREE.Vector3();
          const e = new THREE.Vector3();
          const w = new THREE.Vector3();
          ua.getWorldPosition(s);
          la.getWorldPosition(e);
          ha.getWorldPosition(w);
          const upperLen = s.distanceTo(e);
          const lowerLen = e.distanceTo(w);
          if (upperLen < 1e-4 || lowerLen < 1e-4) return null;
          // Rest world orientations of the NORMALIZED bones (identity in
          // the model's own frame, but the whole scene may be rotated —
          // e.g. the 180° VRM0 flip). Solved goals are built in world axes
          // and must be conjugated through these, otherwise every rotation
          // applies mirrored and the arm swings out behind the body.
          const qParentU = new THREE.Quaternion();
          const qRestU = new THREE.Quaternion();
          const qRestL = new THREE.Quaternion();
          (nua.parent ?? nua).getWorldQuaternion(qParentU);
          nua.getWorldQuaternion(qRestU);
          nla.getWorldQuaternion(qRestL);
          return {
            shoulder: s.clone(),
            upperLen,
            lowerLen,
            restUpperDir: e.clone().sub(s).normalize(),
            restLowerDir: w.clone().sub(e).normalize(),
            qParentUInv: qParentU.clone().invert(),
            qRestU: qRestU.clone(),
            qRestL: qRestL.clone(),
          };
        })();
        // Wrist rests just in front of the chin, on her right side; the
        // pole pulls the elbow down-forward. Reach-capped so a short chibi
        // arm still produces a bent, natural pose.
        const thinkWrist = new THREE.Vector3();
        if (ikGeom) {
          // Beside the chin, below the mouth line — near the face without
          // ever covering it.
          const chin = new THREE.Vector3(
            ikGeom.shoulder.x * 0.85,
            headPos.y - 0.18 * torso,
            0.3 * torso,
          );
          const toChin = chin.sub(ikGeom.shoulder);
          const maxReach = 0.88 * (ikGeom.upperLen + ikGeom.lowerLen);
          if (toChin.length() > maxReach) toChin.setLength(maxReach);
          thinkWrist.copy(ikGeom.shoulder).add(toChin);
        }
        const ikPole = new THREE.Vector3(-0.3, -0.8, 0.5).normalize();
        // Twist about the forearm axis: IK aiming leaves the palm facing an
        // arbitrary way; this rolls the hand so the knuckles face the
        // camera and the fingers curl toward the chin instead of flipping
        // up across the mouth.
        const IK_FOREARM_TWIST = 0.9;

        // ── Finger curl ─────────────────────────────────────────────────
        // VRM hands rest flat-open, which reads robotic. A soft curl runs
        // always; thinking deepens it into a loose fist with the index
        // more extended (classic hand-to-chin). [bone, curl factor].
        const FINGER_CHAIN: Array<[string, number]> = [
          ['rightIndexProximal', 0.35],
          ['rightIndexIntermediate', 0.45],
          ['rightIndexDistal', 0.3],
          ['rightMiddleProximal', 1.0],
          ['rightMiddleIntermediate', 1.15],
          ['rightMiddleDistal', 0.8],
          ['rightRingProximal', 1.05],
          ['rightRingIntermediate', 1.2],
          ['rightRingDistal', 0.85],
          ['rightLittleProximal', 1.1],
          ['rightLittleIntermediate', 1.25],
          ['rightLittleDistal', 0.9],
          ['rightThumbMetacarpal', 0.2],
          ['rightThumbProximal', 0.3],
          ['rightThumbDistal', 0.25],
        ];
        const fingerBones = FINGER_CHAIN.map(([name, factor]) => ({
          node: (vrm.humanoid?.getNormalizedBoneNode?.(name) ?? null) as {
            rotation: { set: (x: number, y: number, z: number) => void };
          } | null,
          factor,
        })).filter((f) => f.node);
        let fingerCurl = 0.3;
        // Scratch for the per-frame solve (no per-frame allocation).
        const vDir = new THREE.Vector3();
        const vBend = new THREE.Vector3();
        const vN = new THREE.Vector3();
        const vElbow = new THREE.Vector3();
        const vTmp = new THREE.Vector3();
        const qUpperGoal = new THREE.Quaternion();
        const qLowerGoal = new THREE.Quaternion();
        const qScratch = new THREE.Quaternion();
        const qTwist = new THREE.Quaternion();
        const ikQUpper = new THREE.Quaternion();
        const ikQLower = new THREE.Quaternion();
        let ikWasActive = false;
        /** Solve the 2-bone chain toward `target`; writes qUpperGoal (local
         *  ≈ world, ancestors are near-identity) and qLowerGoal (local). */
        const solveRightArm = (target: InstanceType<typeof THREE.Vector3>) => {
          if (!ikGeom) return false;
          vDir.copy(target).sub(ikGeom.shoulder);
          const d = Math.min(
            Math.max(vDir.length(), 1e-3),
            ikGeom.upperLen + ikGeom.lowerLen - 1e-4,
          );
          vDir.normalize();
          // Bend direction: perpendicular to the shoulder→target axis, on
          // the pole side.
          vN.crossVectors(vDir, ikPole);
          if (vN.lengthSq() < 1e-6) vN.set(0, 0, 1);
          vN.normalize();
          vBend.crossVectors(vN, vDir).normalize();
          const cosA =
            (ikGeom.upperLen * ikGeom.upperLen + d * d - ikGeom.lowerLen * ikGeom.lowerLen) /
            (2 * ikGeom.upperLen * d);
          const a = Math.acos(Math.min(1, Math.max(-1, cosA)));
          vElbow
            .copy(ikGeom.shoulder)
            .addScaledVector(vDir, Math.cos(a) * ikGeom.upperLen)
            .addScaledVector(vBend, Math.sin(a) * ikGeom.upperLen);
          // Upper arm world-axis rotation: rest dir → shoulder-to-elbow.
          vTmp.copy(vElbow).sub(ikGeom.shoulder).normalize();
          qScratch.setFromUnitVectors(ikGeom.restUpperDir, vTmp); // qU_world
          // Local = parentWorld⁻¹ · qU_world · restWorld.
          qUpperGoal.copy(ikGeom.qParentUInv).multiply(qScratch).multiply(ikGeom.qRestU);
          // Upper arm's new world orientation, for the forearm's parent.
          const qUpperWorldNew = qScratch.clone().multiply(ikGeom.qRestU);
          // Forearm world-axis rotation: rest dir → elbow-to-wrist, then a
          // controlled roll about the new forearm axis for palm direction.
          vTmp.copy(ikGeom.shoulder).addScaledVector(vDir, d).sub(vElbow).normalize();
          qScratch.setFromUnitVectors(ikGeom.restLowerDir, vTmp); // qL_world
          qTwist.setFromAxisAngle(vTmp, IK_FOREARM_TWIST);
          qScratch.premultiply(qTwist);
          qLowerGoal
            .copy(qUpperWorldNew)
            .invert()
            .multiply(qScratch)
            .multiply(ikGeom.qRestL);
          return true;
        };

        // ── Look-at target (eyes)
        const lookTarget = new THREE.Object3D();
        lookTarget.position.set(0, headPos.y, 1.4);
        scene.add(lookTarget);
        if (vrm.lookAt) vrm.lookAt.target = lookTarget;

        // ── Sizing ──────────────────────────────────────────────────────
        const resize = () => {
          const w = host.clientWidth || 300;
          const h = host.clientHeight || 400;
          renderer.setSize(w, h, false);
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
        };
        resize();
        const ro = new ResizeObserver(resize);
        ro.observe(host);
        host.appendChild(renderer.domElement);

        // ── Animation state ─────────────────────────────────────────────
        const bones: Partial<
          Record<BoneKey, { rotation: { set: (x: number, y: number, z: number) => void } } | null>
        > = {};
        const cur: Record<BoneKey, { x: number; y: number; z: number }> = {} as never;
        // Seed the solver at the current pose so she appears already in
        // position (never a T-pose easing in on first paint).
        const seedTargets = POSES[poseRef.current];
        for (const k of BONE_KEYS) {
          bones[k] = vrm.humanoid?.getNormalizedBoneNode?.(k) ?? null;
          const [sx, sy, sz] = seedTargets[k] ?? ZERO;
          cur[k] = { x: sx, y: sy, z: sz };
        }
        const em = vrm.expressionManager;
        // Manual frame timing (THREE.Clock is deprecated in this three release).
        let lastNow = performance.now();
        let elapsed = 0;
        let lip = 0;
        let happy = 0.12;
        let surprised = 0;
        let nextBlinkAt = 2 + Math.random() * 3;
        let blinkPhase: 'open' | 'closing' | 'opening' = 'open';
        let blinkT = 0;
        let blinkValue = 0;
        let doubleBlink = false;
        // Listening behavior loop state. A dev-only URL param pins the
        // phase so headless screenshots can capture each one.
        const devParams = new URLSearchParams(window.location.search);
        const pinnedPhase = devParams.get('phase') as ListenPhase | null;
        // Dev-only: ?snap=1 makes the pose solver converge instantly so
        // headless screenshots (which run only a few rAF frames under
        // virtual time) capture the settled pose instead of a transition.
        const snap = devParams.has('snap');
        // Dev-only: ?vowel=aa|ih|ou|ee|oh pins the viseme for screenshots.
        const pinnedVowel = VOWEL_CENTROIDS[devParams.get('vowel') ?? ''] ?? null;
        let centroidSm = 0.5;
        const vowelW = new Array(VOWEL_BANDS.length).fill(0) as number[];
        let listenPhase: ListenPhase = 'attentive';
        let prevPose: AvatarPose | null = null;
        let nextJotAt = 0;
        let jotUntil = 0;
        let reassureUntil = 0;
        let nextNodAt = 0;
        let nodStart = -10;

        const tick = () => {
          const now = performance.now();
          // Clamp: max guards tab-switch gaps; min keeps the pose solver
          // advancing when rAF outpaces wall-clock (high-refresh displays,
          // headless virtual-time screenshots).
          const dt = Math.min(Math.max((now - lastNow) / 1000, 1 / 144), 0.1);
          lastNow = now;
          elapsed += dt;
          const t = elapsed;
          const pose = poseRef.current;
          const still = reduceRef.current;
          const k = still || snap ? 1 : 1 - Math.exp(-7 * dt);

          // ── Listening behavior loop: attentive → jot → reassure ────────
          if (pose !== prevPose) {
            prevPose = pose;
            listenPhase = 'attentive';
            nextJotAt = t + JOT_AFTER_MIN + Math.random() * JOT_AFTER_VAR;
            nextNodAt = t + 2 + Math.random() * 2;
          }
          if (pose === 'listening' && !still) {
            if (listenPhase === 'attentive' && t >= nextJotAt) {
              listenPhase = 'jot';
              jotUntil = t + JOT_LEN_MIN + Math.random() * JOT_LEN_VAR;
            } else if (listenPhase === 'jot' && t >= jotUntil) {
              listenPhase = 'reassure';
              reassureUntil = t + REASSURE_LEN;
            } else if (listenPhase === 'reassure' && t >= reassureUntil) {
              listenPhase = 'attentive';
              nextJotAt = t + JOT_AFTER_MIN + Math.random() * JOT_AFTER_VAR;
              nextNodAt = t + 1.5;
            }
          }
          const phase: ListenPhase = pinnedPhase ?? listenPhase;
          const overrides = pose === 'listening' ? LISTEN_OVERRIDES[phase] : undefined;
          const targets = POSES[pose];

          // The raised thinking arm is solved by IK; those two bones skip
          // the Euler path while it is active.
          const ikActive = pose === 'thinking' && !!ikGeom;

          for (const bkey of BONE_KEYS) {
            if (ikActive && (bkey === 'rightUpperArm' || bkey === 'rightLowerArm')) continue;
            const node = bones[bkey];
            const target = overrides?.[bkey] ?? targets[bkey] ?? ZERO;
            if (!node) continue;
            // The humanoid resets the normalized rig each update, so the
            // smoothed pose lives in `cur` and is written out absolutely.
            const r = cur[bkey];
            let [tx, ty, tz] = target;
            if (!still) {
              // Additive layers on top of the pose target.
              const breath = Math.sin(t * 1.96);
              if (bkey === 'chest') tx += breath * 0.015;
              if (bkey === 'head') tx += breath * 0.006;
              if (pose === 'listening' && phase === 'attentive' && bkey === 'head') {
                // Slow affirming nod every few seconds.
                if (t >= nextNodAt) {
                  nodStart = t;
                  nextNodAt = t + 3.5 + Math.random() * 2.5;
                }
                const nodT = t - nodStart;
                if (nodT < 0.9) tx += Math.sin((nodT / 0.9) * Math.PI) * 0.09;
              }
              if (pose === 'listening' && phase === 'jot') {
                // Tiny writing motion — below the frame; the visible story
                // is the bowed head plus a whisper of shoulder movement.
                if (bkey === 'rightHand') tz += Math.sin(t * 10) * 0.1;
                if (bkey === 'rightLowerArm') ty += Math.sin(t * 10 + 0.5) * 0.04;
                if (bkey === 'rightShoulder') tz += Math.sin(t * 10) * 0.01;
              }
              if (pose === 'speaking' && bkey === 'head') {
                tx += lip * 0.05 + Math.sin(t * 4.2) * 0.012 * lip;
              }
              if (pose === 'thinking' && bkey === 'head') {
                tz += Math.sin(t * 0.55) * 0.02;
              }
            }
            r.x += (tx - r.x) * k;
            r.y += (ty - r.y) * k;
            r.z += (tz - r.z) * k;
            node.rotation.set(r.x, r.y, r.z);
          }

          // ── IK application + smooth handoff with the Euler path ────────
          if (ikActive) {
            const ua = bones.rightUpperArm as unknown as {
              quaternion: InstanceType<typeof THREE.Quaternion>;
            } | null;
            const la = bones.rightLowerArm as unknown as {
              quaternion: InstanceType<typeof THREE.Quaternion>;
            } | null;
            if (ua && la && solveRightArm(thinkWrist)) {
              if (!ikWasActive) {
                // Entering IK: start the slerp from the Euler pose so the
                // arm glides up instead of popping.
                ikQUpper.setFromEuler(
                  new THREE.Euler(cur.rightUpperArm.x, cur.rightUpperArm.y, cur.rightUpperArm.z),
                );
                ikQLower.setFromEuler(
                  new THREE.Euler(cur.rightLowerArm.x, cur.rightLowerArm.y, cur.rightLowerArm.z),
                );
              }
              ikQUpper.slerp(qUpperGoal, k);
              ikQLower.slerp(qLowerGoal, k);
              ua.quaternion.copy(ikQUpper);
              la.quaternion.copy(ikQLower);
            }
          } else if (ikWasActive) {
            // Leaving IK: hand the current orientation back to the Euler
            // solver so it eases down from where the arm actually is.
            const e = new THREE.Euler().setFromQuaternion(ikQUpper, 'XYZ');
            cur.rightUpperArm.x = e.x;
            cur.rightUpperArm.y = e.y;
            cur.rightUpperArm.z = e.z;
            e.setFromQuaternion(ikQLower, 'XYZ');
            cur.rightLowerArm.x = e.x;
            cur.rightLowerArm.y = e.y;
            cur.rightLowerArm.z = e.z;
          }
          ikWasActive = ikActive;

          // Fingers: soft curl everywhere, loose fist (index freer) while
          // the hand is up at the chin. Written every frame — the humanoid
          // resets the normalized rig on update.
          const curlTarget = pose === 'thinking' ? 1.0 : 0.3;
          fingerCurl += (curlTarget - fingerCurl) * k;
          for (const f of fingerBones) f.node!.rotation.set(0, 0, fingerCurl * f.factor);

          // Eyes: glide the look target toward the pose's offset.
          const off = LOOK_OFFSETS[pose === 'listening' && phase === 'jot' ? 'jot' : pose];
          lookTarget.position.x += (off[0] * propScale - lookTarget.position.x) * k;
          lookTarget.position.y += (headPos.y + off[1] * propScale - lookTarget.position.y) * k;
          lookTarget.position.z += (off[2] * propScale - lookTarget.position.z) * k;

          // Lip sync: loudness = mouth openness (fast attack, slower
          // decay); spectral centroid = which vowel shape, blended across
          // the five VRM visemes with overlapping bands.
          let level = 0;
          let centroidTarget = 0.5;
          if (pose === 'speaking' && !still) {
            const feats = getFeaturesRef.current?.();
            if (feats) {
              level = feats.level;
              if (level > 0.02) centroidTarget = feats.centroid;
            } else {
              level = getLevelRef.current?.() ?? 0;
            }
          }
          if (pinnedVowel !== null) {
            centroidTarget = pinnedVowel;
            if (pose === 'speaking') level = Math.max(level, 0.6);
          }
          lip += (level - lip) * (1 - Math.exp(-dt * (level > lip ? 26 : 8)));
          centroidSm += (centroidTarget - centroidSm) * (1 - Math.exp(-dt * 12));
          const open = Math.min(1, lip * 1.5);
          let wSum = 0;
          for (let i = 0; i < VOWEL_BANDS.length; i++) {
            const [, center, width] = VOWEL_BANDS[i];
            vowelW[i] = Math.max(0, 1 - Math.abs(centroidSm - center) / width);
            wSum += vowelW[i];
          }
          for (let i = 0; i < VOWEL_BANDS.length; i++) {
            const w = wSum > 1e-4 ? (vowelW[i] / wSum) * open : 0;
            em?.setValue?.(VOWEL_BANDS[i][0], w);
          }

          // Blink state machine (skipped under reduced motion).
          if (!still) {
            if (blinkPhase === 'open' && t >= nextBlinkAt) {
              blinkPhase = 'closing';
              blinkT = 0;
              doubleBlink = Math.random() < 0.18;
            } else if (blinkPhase === 'closing') {
              blinkT += dt;
              blinkValue = Math.min(1, blinkT / 0.06);
              if (blinkValue >= 1) {
                blinkPhase = 'opening';
                blinkT = 0;
              }
            } else if (blinkPhase === 'opening') {
              blinkT += dt;
              blinkValue = Math.max(0, 1 - blinkT / 0.09);
              if (blinkValue <= 0) {
                blinkPhase = 'open';
                nextBlinkAt = t + (doubleBlink ? 0.25 : 2.8 + Math.random() * 3.2);
                doubleBlink = false;
              }
            }
            em?.setValue?.('blink', blinkValue);
          }
          // Expressions cross-fade smoothly: warm by default, beaming for
          // the post-jot reassure moment, a hint of wonder while thinking.
          const happyTarget =
            pose === 'listening'
              ? phase === 'reassure'
                ? 0.8
                : phase === 'jot'
                  ? 0.08
                  : HAPPY_TARGETS.listening
              : HAPPY_TARGETS[pose];
          const ke = still || snap ? 1 : 1 - Math.exp(-5 * dt);
          happy += (happyTarget - happy) * ke;
          surprised += ((pose === 'thinking' ? 0.12 : 0) - surprised) * ke;
          em?.setValue?.('happy', happy);
          em?.setValue?.('surprised', surprised);

          vrm.update(dt);
          renderer.render(scene, camera);
        };
        renderer.setAnimationLoop(tick);

        // The kiosk runs 24/7 — halt the loop while the tab is hidden.
        const onVis = () => {
          renderer.setAnimationLoop(document.hidden ? null : tick);
          if (!document.hidden) lastNow = performance.now(); // swallow the hidden gap
        };
        document.addEventListener('visibilitychange', onVis);

        dispose = () => {
          document.removeEventListener('visibilitychange', onVis);
          ro.disconnect();
          renderer.setAnimationLoop(null);
          renderer.domElement.remove();
          VRMUtils.deepDispose(vrm.scene);
          renderer.dispose();
        };
        setReady(true);
      } catch {
        if (!disposed) setFailed(true);
      }
    })();

    return () => {
      disposed = true;
      dispose?.();
    };
  }, []);

  if (failed) {
    return <NurseAvatar state={state} getLevel={getLevel} />;
  }

  return (
    <div
      style={{ position: 'relative', width: '100%', height: '100%' }}
      role="img"
      aria-label={`assistant ${state}`}
    >
      {!ready && <NurseAvatar state={state} getLevel={getLevel} />}
      <div
        ref={hostRef}
        style={{
          position: 'absolute',
          inset: 0,
          opacity: ready ? 1 : 0,
          transition: 'opacity 300ms ease',
        }}
      />
    </div>
  );
}

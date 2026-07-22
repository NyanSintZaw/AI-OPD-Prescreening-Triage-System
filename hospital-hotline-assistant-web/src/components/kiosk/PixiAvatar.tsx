import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Application, Assets, Container, Sprite, Texture } from 'pixi.js';
import gsap from 'gsap';
import type { VoiceCallState } from '../../hooks/useVoiceCall';

/**
 * PixiJS + GSAP cut-out puppet for the kiosk nurse.
 *
 * Loads the layered PNG pack described by /avatar/layers/manifest.json — every
 * body part is its own transparent, globally-aligned sprite, so stacking them
 * at (0,0) reproduces the character exactly. Each node's pivot == position ==
 * its joint, which means the rig is a perfect stack at rest AND every part
 * rotates / scales about the correct hinge (neck, shoulders, elbows, jaw).
 *
 * The `state` prop drives the base pose (idle / listening=writing /
 * thinking / speaking); `getLevel` (live TTS loudness 0..1) drives amplitude
 * lip-sync. One-shot gestures are exposed through the imperative ref.
 *
 * Falls back to `fallback` (e.g. the SVG <NurseAvatar/>) if the pack or WebGL
 * fails to load, so the tile is never empty.
 */

const BASE = '/avatar/layers/';

type Pose = 'idle' | 'listening' | 'thinking' | 'speaking';

export interface PixiAvatarHandle {
  play: (g: 'wave' | 'thumbsUp' | 'headScratch' | 'happyBounce' | 'nod') => void;
  look: (dir: -1 | 0 | 1) => void;
}

interface PixiAvatarProps {
  state: VoiceCallState | 'idle';
  /** Identity-stable live loudness getter (useVoiceCall.getOutputLevel). */
  getLevel?: () => number;
  fallback?: ReactNode;
}

interface ManifestLayer {
  name: string;
  filename: string;
  pivot: { x: number; y: number };
  defaultPosition: { x: number; y: number };
  zIndex: number;
  parent: string;
}
interface Manifest {
  canvas: [number, number];
  scale: number;
  layers: ManifestLayer[];
}

function toPose(state: VoiceCallState | 'idle'): Pose {
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

// Amplitude → mouth phoneme thresholds (same spirit as SpriteAvatar).
const TALK_MID = 0.09;
const TALK_OPEN = 0.34;

export const PixiAvatar = forwardRef<PixiAvatarHandle, PixiAvatarProps>(function PixiAvatar(
  { state, getLevel, fallback },
  ref,
) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);

  // Everything the animation loops need, collected once the rig is built.
  const rig = useRef<{
    app: Application;
    root: Container;
    world: Container;
    groups: Record<string, Container>;
    sprites: Record<string, Sprite>;
    // mutually-exclusive visual sets
    setEyes: (n: 'eyes_open' | 'eyes_closed' | 'eyes_happy' | 'eyes_confused') => void;
    setBrows: (n: 'eyebrows_normal' | 'eyebrows_happy' | 'eyebrows_confused') => void;
    setMouth: (n: string) => void;
    kill: () => void;
  } | null>(null);

  const poseRef = useRef<Pose>('idle');
  const levelRef = useRef<typeof getLevel>(getLevel);
  levelRef.current = getLevel;

  // ── Build the rig once ────────────────────────────────────────────────────
  useEffect(() => {
    let disposed = false;
    const app = new Application();
    const timelines: gsap.core.Tween[] = [];
    let rafId = 0;

    (async () => {
      try {
        const host = hostRef.current;
        if (!host) return;
        await app.init({
          backgroundAlpha: 0,
          antialias: true,
          resolution: Math.min(window.devicePixelRatio || 1, 2),
          autoDensity: true,
          resizeTo: host,
        });
        if (disposed) {
          app.destroy(true);
          return;
        }
        host.appendChild(app.canvas as HTMLCanvasElement);
        app.canvas.style.width = '100%';
        app.canvas.style.height = '100%';
        (app.canvas as HTMLCanvasElement).style.display = 'block';

        const manifest = (await (await fetch(`${BASE}manifest.json`, { cache: 'no-cache' })).json()) as Manifest;
        const [CW, CH] = manifest.canvas;

        // Load every texture up front.
        const assetMap: Record<string, string> = {};
        manifest.layers.forEach((l) => (assetMap[l.name] = BASE + l.filename));
        const textures = (await Assets.load(Object.values(assetMap))) as Record<string, Texture>;
        if (disposed) {
          app.destroy(true);
          return;
        }

        // root scales the 600x800 art to fit the tile; world = breathing hinge.
        const root = new Container();
        const world = new Container();
        world.pivot.set(CW / 2, CH); // bottom-centre
        world.position.set(CW / 2, CH);
        root.addChild(world);
        app.stage.addChild(root);

        // Parent containers, each hinged at its own joint so rotating the
        // container swings the whole limb / head about the right point.
        const groupJoints: Record<string, { x: number; y: number }> = {
          body: { x: 0, y: 0 },
          board: { x: 162, y: 356 },
          leftArm: { x: 70, y: 300 },
          rightArm: { x: 230, y: 300 },
          head: { x: 150, y: 262 },
          fx: { x: 0, y: 0 },
        };
        // headBob rides the breath and is NEVER touched by pose/gesture tweens,
        // so ambient motion and pose changes can't fight over the head group.
        const headBob = new Container();
        headBob.zIndex = 40;
        world.addChild(headBob);

        const groups: Record<string, Container> = {};
        (['body', 'board', 'leftArm', 'rightArm', 'head', 'fx'] as const).forEach((g) => {
          const c = new Container();
          c.sortableChildren = true;
          const j = groupJoints[g];
          c.pivot.set(j.x * manifest.scale, j.y * manifest.scale);
          c.position.set(j.x * manifest.scale, j.y * manifest.scale);
          groups[g] = c;
          if (g === 'head') headBob.addChild(c);
          else world.addChild(c);
        });
        world.sortableChildren = true;
        groups.body.zIndex = 20;
        groups.board.zIndex = 30;
        groups.leftArm.zIndex = 33;
        groups.rightArm.zIndex = 34;
        groups.fx.zIndex = 60;

        // Place every layer as a sprite. pivot == position == joint → the art
        // lands in its true global spot yet spins/scales about its hinge.
        const sprites: Record<string, Sprite> = {};
        // clipboard + paper belong to the board group even though the manifest
        // files them under "body".
        const parentOverride: Record<string, string> = { clipboard: 'board', paper: 'board' };
        manifest.layers.forEach((l) => {
          const tex = textures[assetMap[l.name]] ?? Texture.from(assetMap[l.name]);
          const s = new Sprite(tex);
          s.anchor.set(0);
          s.pivot.set(l.pivot.x, l.pivot.y);
          s.position.set(l.defaultPosition.x, l.defaultPosition.y);
          s.zIndex = l.zIndex;
          sprites[l.name] = s;
          const parentKey = parentOverride[l.name] ?? l.parent;
          (groups[parentKey] ?? groups.body).addChild(s);
        });

        // hair_back / neck / body sit in the body group; make sure body group
        // draws them in z order.
        groups.body.sortableChildren = true;
        groups.head.sortableChildren = true;

        // Mutually-exclusive visual sets: show one, hide the siblings.
        const eyeSet = ['eyes_open', 'eyes_closed', 'eyes_happy', 'eyes_confused'];
        const browSet = ['eyebrows_normal', 'eyebrows_happy', 'eyebrows_confused'];
        const mouthSet = ['mouth_closed', 'mouth_smile', 'mouth_A', 'mouth_E', 'mouth_I', 'mouth_O', 'mouth_U'];
        const showOne = (set: string[], name: string) =>
          set.forEach((n) => {
            if (sprites[n]) sprites[n].visible = n === name;
          });
        const setEyes = (n: any) => showOne(eyeSet, n);
        const setBrows = (n: any) => showOne(browSet, n);
        const setMouth = (n: string) => {
          showOne(mouthSet, n);
          if (sprites[n]) sprites[n].scale.set(1); // clear any lip-sync jaw scale
        };
        setEyes('eyes_open');
        setBrows('eyebrows_normal');
        setMouth('mouth_closed');
        // Hidden by default: effects (shown only while thinking) and the
        // optional standalone side-hair pieces (the fringe layer already
        // includes the wisps — these exist for rigs that want to animate the
        // sides independently).
        ['lightbulb', 'sparkle', 'left_hair', 'right_hair'].forEach((n) => sprites[n] && (sprites[n].visible = false));

        // Fit root into the tile whenever it resizes.
        const fit = () => {
          const w = app.renderer.width / app.renderer.resolution;
          const h = app.renderer.height / app.renderer.resolution;
          const s = Math.min(w / CW, h / CH);
          root.scale.set(s);
          root.position.set((w - CW * s) / 2, (h - CH * s) / 2);
        };
        fit();
        const ro = new ResizeObserver(fit);
        ro.observe(host);

        // ── Ambient loops ──────────────────────────────────────────────────
        // Idle breathing — the whole figure swells about its base.
        timelines.push(
          gsap.to(world.scale, { x: 1.006, y: 1.014, duration: 3.6, ease: 'sine.inOut', yoyo: true, repeat: -1 }),
        );
        // Gentle head bob rides on the breath (on headBob, so pose tweens on
        // groups.head never cancel it).
        timelines.push(
          gsap.to(headBob, {
            y: `+=${3 * manifest.scale}`,
            duration: 3.6,
            ease: 'sine.inOut',
            yoyo: true,
            repeat: -1,
          }),
        );

        // Random blink — quick close, then restore to whatever eyes the pose wants.
        const poseEyes = () =>
          poseRef.current === 'thinking' ? 'eyes_confused' : poseRef.current === 'idle' || poseRef.current === 'listening' ? 'eyes_open' : 'eyes_open';
        const blink = () => {
          if (disposed) return;
          setEyes('eyes_closed');
          gsap.delayedCall(0.12, () => !disposed && setEyes(poseEyes() as any));
          gsap.delayedCall(2.6 + Math.random() * 3.4, blink);
        };
        gsap.delayedCall(2.6 + Math.random() * 3.4, blink);

        rig.current = {
          app,
          root,
          world,
          groups,
          sprites,
          setEyes,
          setBrows,
          setMouth,
          kill: () => {
            ro.disconnect();
            timelines.forEach((t) => t.kill());
            gsap.killTweensOf([world, world.scale, groups.head, groups.leftArm, groups.rightArm, groups.board, sprites.pen, sprites.eyes_open, sprites.mouth_A]);
            cancelAnimationFrame(rafId);
          },
        };

        // Apply the initial pose.
        applyPose(poseRef.current);

        // ── Amplitude lip-sync loop (always running; no-ops unless speaking) ─
        let smoothed = 0;
        const tick = () => {
          const r = rig.current;
          if (r && poseRef.current === 'speaking') {
            const get = levelRef.current;
            const target = get ? get() : 0;
            smoothed += (target - smoothed) * (target > smoothed ? 0.5 : 0.22);
            const m = smoothed >= TALK_OPEN ? 'mouth_A' : smoothed >= TALK_MID ? 'mouth_E' : 'mouth_closed';
            r.setMouth(m);
            const jaw = r.sprites[m];
            if (jaw) jaw.scale.y = 0.9 + smoothed * 0.35;
          }
          rafId = requestAnimationFrame(tick);
        };
        rafId = requestAnimationFrame(tick);
      } catch (err) {
        console.warn('[PixiAvatar] failed to build rig, falling back:', err);
        if (!disposed) setFailed(true);
        try {
          app.destroy(true);
        } catch {
          /* already gone */
        }
      }
    })();

    return () => {
      disposed = true;
      rig.current?.kill();
      rig.current = null;
      gsap.globalTimeline.getChildren().forEach(() => {});
      try {
        app.destroy(true, { children: true, texture: false });
      } catch {
        /* ignore */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Pose transitions (smooth GSAP tweens between states) ──────────────────
  function applyPose(pose: Pose) {
    const r = rig.current;
    if (!r) return;
    const { groups, sprites, setEyes, setBrows, setMouth } = r;
    const ease = 'power2.out';
    // Reset transient effects/gestures.
    gsap.killTweensOf([groups.head, groups.leftArm, groups.rightArm, groups.board, sprites.pen]);
    sprites.lightbulb.visible = false;
    sprites.sparkle.visible = false;
    groups.leftArm.zIndex = 33;

    if (pose === 'idle') {
      setEyes('eyes_open');
      setBrows('eyebrows_normal');
      setMouth('mouth_closed');
      gsap.to(groups.head, { rotation: 0, duration: 0.5, ease });
      gsap.to(groups.leftArm, { rotation: 0, duration: 0.5, ease });
      gsap.to(groups.rightArm, { rotation: 0, duration: 0.5, ease });
      gsap.to(sprites.pen, { rotation: 0, duration: 0.4, ease });
    } else if (pose === 'listening') {
      // Writing: head tips toward the clipboard, pen scribbles.
      setEyes('eyes_open');
      setBrows('eyebrows_normal');
      setMouth('mouth_closed');
      gsap.to(groups.head, { rotation: -0.1, duration: 0.5, ease });
      gsap.to(groups.leftArm, {
        rotation: 0.06,
        duration: 0.5,
        ease,
        onComplete: () => {
          gsap.to(groups.leftArm, { rotation: -0.03, duration: 0.28, yoyo: true, repeat: -1, ease: 'sine.inOut' });
          gsap.to(sprites.pen, { rotation: 0.18, duration: 0.2, yoyo: true, repeat: -1, ease: 'sine.inOut' });
          gsap.to(groups.board, { rotation: 0.015, y: `+=${2}`, duration: 1.4, yoyo: true, repeat: -1, ease: 'sine.inOut' });
        },
      });
    } else if (pose === 'thinking') {
      // Pen lifts to the chin, "o" mouth, eyes glance up, lightbulb + sparkle.
      setEyes('eyes_confused');
      setBrows('eyebrows_confused');
      setMouth('mouth_O');
      groups.leftArm.zIndex = 45; // pen reads in front while at the chin
      gsap.to(groups.head, { rotation: 0.07, duration: 0.5, ease });
      gsap.to(groups.leftArm, { rotation: -1.0, duration: 0.6, ease: 'back.out(1.4)' });
      gsap.to(sprites.pen, { rotation: -0.3, duration: 0.5, ease });
      sprites.lightbulb.visible = true;
      sprites.sparkle.visible = true;
      sprites.lightbulb.alpha = 0;
      sprites.sparkle.alpha = 0;
      gsap.to([sprites.lightbulb, sprites.sparkle], { alpha: 1, duration: 0.4, stagger: 0.1 });
      gsap.to(sprites.lightbulb.scale, { x: 1.12, y: 1.12, duration: 0.9, yoyo: true, repeat: -1, ease: 'sine.inOut' });
    } else if (pose === 'speaking') {
      setEyes('eyes_open');
      setBrows('eyebrows_normal');
      setMouth('mouth_closed'); // the rAF loop takes over the mouth
      gsap.to(groups.head, { rotation: 0, duration: 0.4, ease });
      gsap.to(groups.leftArm, { rotation: 0, duration: 0.4, ease });
      gsap.to(sprites.pen, { rotation: 0, duration: 0.4, ease });
    }
  }

  useEffect(() => {
    const pose = toPose(state);
    poseRef.current = pose;
    applyPose(pose);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  // ── One-shot gestures via ref ─────────────────────────────────────────────
  useImperativeHandle(
    ref,
    (): PixiAvatarHandle => ({
      look: (dir) => {
        const r = rig.current;
        if (!r) return;
        // Rest x of any sprite equals its pivot.x (pivot == position), so a
        // glance is pivot.x + delta — never an absolute jump to the delta.
        ['eyes_open', 'eyes_confused', 'eyes_happy'].forEach(
          (n) => r.sprites[n] && gsap.to(r.sprites[n], { x: r.sprites[n].pivot.x + dir * 7, duration: 0.35, ease: 'power2.out' }),
        );
        gsap.to(r.groups.head, { rotation: dir * 0.05, duration: 0.4, ease: 'power2.out' });
      },
      play: (g) => {
        const r = rig.current;
        if (!r) return;
        const { groups, setEyes, setBrows, setMouth } = r;
        if (g === 'nod') {
          gsap.timeline().to(groups.head, { y: `+=${6}`, rotation: -0.04, duration: 0.22, ease: 'power2.inOut' }).to(groups.head, { y: `-=${6}`, rotation: 0, duration: 0.28, ease: 'power2.out' });
        } else if (g === 'happyBounce') {
          setEyes('eyes_happy');
          setBrows('eyebrows_happy');
          setMouth('mouth_smile');
          gsap
            .timeline({ onComplete: () => applyPose(poseRef.current) })
            .to(r.world, { y: `-=${18}`, duration: 0.22, ease: 'power2.out' })
            .to(r.world, { y: `+=${18}`, duration: 0.5, ease: 'bounce.out' });
        } else if (g === 'wave') {
          // Right arm swings up and waves a few times, then returns.
          gsap
            .timeline({ onComplete: () => gsap.to(groups.rightArm, { rotation: 0, duration: 0.4, ease: 'power2.out' }) })
            .to(groups.rightArm, { rotation: -0.9, duration: 0.35, ease: 'back.out(1.6)' })
            .to(groups.rightArm, { rotation: -0.65, duration: 0.18, yoyo: true, repeat: 5, ease: 'sine.inOut' });
        } else if (g === 'thumbsUp') {
          // No dedicated thumb art — approximate with a confident arm pop.
          gsap
            .timeline({ onComplete: () => gsap.to(groups.rightArm, { rotation: 0, duration: 0.4, ease: 'power2.out' }) })
            .to(groups.rightArm, { rotation: -0.7, duration: 0.3, ease: 'back.out(2)' })
            .to(groups.rightArm, { rotation: -0.6, duration: 0.4 });
          setEyes('eyes_happy');
          setBrows('eyebrows_happy');
          gsap.delayedCall(1.0, () => applyPose(poseRef.current));
        } else if (g === 'headScratch') {
          setEyes('eyes_confused');
          setBrows('eyebrows_confused');
          setMouth('mouth_O');
          gsap
            .timeline({ onComplete: () => applyPose(poseRef.current) })
            .to(groups.head, { rotation: 0.09, duration: 0.4, ease: 'power2.out' }, 0)
            .to(groups.rightArm, { rotation: -1.15, duration: 0.4, ease: 'power2.out' }, 0)
            .to(groups.rightArm, { rotation: -1.0, duration: 0.16, yoyo: true, repeat: 5, ease: 'sine.inOut' })
            .to(groups.rightArm, { rotation: 0, duration: 0.4, ease: 'power2.inOut' })
            .to(groups.head, { rotation: 0, duration: 0.4, ease: 'power2.inOut' }, '<');
        }
      },
    }),
    [],
  );

  if (failed) return <>{fallback ?? null}</>;
  return <div ref={hostRef} style={{ width: '100%', height: '100%', display: 'block' }} aria-label={`assistant ${state}`} role="img" />;
});

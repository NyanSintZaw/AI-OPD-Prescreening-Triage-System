# Kiosk Avatar — Art Layer Specification (superseded)

This layer-rig spec is superseded: the kiosk avatar switched to
**frame-based animation** using whole-character pictures instead of a
layered rig. See **[avatar-frames-guide.md](avatar-frames-guide.md)** for
the current workflow (shot list, naming, drop folder, processing script).

The rigged-SVG fallback (`NurseAvatar.tsx`) still exists and renders
whenever no processed frames are present in `public/avatar/`.

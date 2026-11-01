"use client";
import { Canvas, useThree } from "@react-three/fiber";
import { GizmoHelper, GizmoViewport, OrbitControls, OrthographicCamera, PerspectiveCamera } from "@react-three/drei";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { Spinner } from "./ui";

export type DisplayMode = "textured" | "clay" | "wireframe" | "points";
type View = "iso" | "top" | "front" | "side";
type CamType = "persp" | "ortho";

export type Tool = "orbit" | "pick" | "erase";
export interface RegionSelection { matrix: number[]; polygon: [number, number][]; count: number }

interface Props {
  tool?: Tool;
  onPick?: (p: [number, number, number]) => void;
  onRegion?: (r: RegionSelection | null) => void;
  markers?: [number, number, number][];
  cropBox?: { min: [number, number, number]; max: [number, number, number] } | null;
  onBounds?: (b: { min: [number, number, number]; max: [number, number, number] }) => void;
  modelUrl: string;
  fullModelUrl?: string | null;   // offered when the preview is decimated
  pointCloudUrl?: string | null;
  info?: { faces: number; full_faces: number; decimated: boolean; pointcloud_points: number } | null;
  onCapture?: (blob: Blob) => void; // used to store a 3D thumbnail
  autoCapture?: boolean;
}

interface Loaded { object: THREE.Object3D; box: THREE.Box3 }

const VIEW_DIR: Record<View, THREE.Vector3> = {
  iso: new THREE.Vector3(1, 0.75, 1.15).normalize(),
  top: new THREE.Vector3(0, 1, 0.0001).normalize(),
  front: new THREE.Vector3(0, 0, 1),
  side: new THREE.Vector3(1, 0, 0),
};

function disposeObject(o: THREE.Object3D) {
  o.traverse((c) => {
    const m = c as THREE.Mesh;
    m.geometry?.dispose?.();
    const mats = Array.isArray(m.material) ? m.material : m.material ? [m.material] : [];
    for (const mat of mats) {
      for (const v of Object.values(mat)) if (v instanceof THREE.Texture) v.dispose();
      mat.dispose();
    }
  });
}

/** Loads a GLB with real byte progress. Draco is not used: no CDN request. */
function useGLB(url: string | null) {
  const [state, setState] = useState<{ data: Loaded | null; progress: number | null; error: string | null; loading: boolean }>(
    { data: null, progress: null, error: null, loading: !!url });
  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    let loaded: THREE.Object3D | null = null;
    setState({ data: null, progress: null, error: null, loading: true });
    new GLTFLoader().load(
      url,
      (gltf) => {
        if (cancelled) { disposeObject(gltf.scene); return; }
        loaded = gltf.scene;
        gltf.scene.traverse((c) => {
          const m = c as THREE.Mesh;
          if (m.isMesh) {
            if (!m.geometry.attributes.normal) m.geometry.computeVertexNormals();
            m.userData.original = m.material;
          }
        });
        setState({ data: { object: gltf.scene, box: new THREE.Box3().setFromObject(gltf.scene) }, progress: 1, error: null, loading: false });
      },
      (ev) => { if (!cancelled && ev.lengthComputable) setState((s) => ({ ...s, progress: ev.loaded / ev.total })); },
      () => { if (!cancelled) setState({ data: null, progress: null, error: "Impossible de charger le modèle 3D.", loading: false }); },
    );
    return () => { cancelled = true; if (loaded) disposeObject(loaded); };
  }, [url]);
  return state;
}

function usePLY(url: string | null) {
  const [state, setState] = useState<{ geom: THREE.BufferGeometry | null; progress: number | null; error: string | null; loading: boolean }>(
    { geom: null, progress: null, error: null, loading: false });
  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    let g: THREE.BufferGeometry | null = null;
    setState({ geom: null, progress: null, error: null, loading: true });
    new PLYLoader().load(
      url,
      (geom) => { if (cancelled) { geom.dispose(); return; } g = geom; setState({ geom, progress: 1, error: null, loading: false }); },
      (ev) => { if (!cancelled && ev.lengthComputable) setState((s) => ({ ...s, progress: ev.loaded / ev.total })); },
      () => { if (!cancelled) setState({ geom: null, progress: null, error: "Nuage de points indisponible pour ce projet.", loading: false }); },
    );
    return () => { cancelled = true; g?.dispose(); };
  }, [url]);
  return state;
}

const clayMaterial = new THREE.MeshStandardMaterial({ color: 0xc3c8d0, roughness: 0.85, metalness: 0, side: THREE.DoubleSide });
const wireMaterial = new THREE.MeshBasicMaterial({ color: 0x8ab4ff, wireframe: true, transparent: true, opacity: 0.55 });

function applyMode(root: THREE.Object3D, mode: DisplayMode) {
  root.traverse((c) => {
    const m = c as THREE.Mesh;
    if (!m.isMesh) return;
    const orig = m.userData.original as THREE.MeshStandardMaterial;
    if (mode === "textured") {
      // Photogrammetry textures already contain the real lighting: show them unlit.
      if (!m.userData.unlit) {
        m.userData.unlit = new THREE.MeshBasicMaterial({ map: orig?.map ?? null, color: orig?.map ? 0xffffff : (orig?.color ?? 0xcccccc), side: THREE.DoubleSide });
      }
      m.material = m.userData.unlit;
    } else if (mode === "clay") m.material = clayMaterial;
    else m.material = wireMaterial;
  });
}

function CameraRig({ box, view, camType, nonce, controls }: { box: THREE.Box3; view: View; camType: CamType; nonce: number; controls: React.RefObject<any> }) {
  const { camera, size } = useThree();
  useEffect(() => {
    const center = box.getCenter(new THREE.Vector3());
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const r = Math.max(sphere.radius, 1e-3);
    const dir = VIEW_DIR[view];
    if ((camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
      const cam = camera as THREE.PerspectiveCamera;
      const dist = r / Math.sin(THREE.MathUtils.degToRad(cam.fov / 2)) * 0.85;
      cam.position.copy(center).addScaledVector(dir, dist);
      cam.near = dist / 200; cam.far = dist * 20;
    } else {
      const cam = camera as THREE.OrthographicCamera;
      cam.position.copy(center).addScaledVector(dir, r * 4);
      cam.zoom = Math.min(size.width, size.height) / (r * 1.8);
      cam.near = -r * 20; cam.far = r * 20;
    }
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    if (controls.current) { controls.current.target.copy(center); controls.current.update(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [box, view, camType, nonce, camera]);
  return null;
}

function CameraGrab({ target }: { target: React.MutableRefObject<THREE.Camera | null> }) {
  const camera = useThree((s) => s.camera);
  useEffect(() => { target.current = camera; }, [camera, target]);
  return null;
}

function MeasureLine({ a, b }: { a: [number, number, number]; b: [number, number, number] }) {
  const geom = useMemo(() => new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...b)]), [a, b]);
  useEffect(() => () => geom.dispose(), [geom]);
  return <lineSegments geometry={geom}><lineBasicMaterial color="#fbbf24" depthTest={false} /></lineSegments>;
}

function CropBoxView({ box }: { box: { min: [number, number, number]; max: [number, number, number] } }) {
  const b3 = useMemo(() => new THREE.Box3(new THREE.Vector3(...box.min), new THREE.Vector3(...box.max)), [box]);
  const size = b3.getSize(new THREE.Vector3()), center = b3.getCenter(new THREE.Vector3());
  return (
    <group>
      <box3Helper args={[b3, 0x8ab4ff]} />
      <mesh position={center}><boxGeometry args={[size.x, size.y, size.z]} /><meshBasicMaterial color="#8ab4ff" transparent opacity={0.08} depthWrite={false} /></mesh>
    </group>
  );
}

function Invalidate({ deps }: { deps: unknown[] }) {
  const invalidate = useThree((s) => s.invalidate);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { invalidate(); }, deps);
  return null;
}

function Capture({ when, onCapture }: { when: number; onCapture?: (b: Blob) => void }) {
  const { gl, scene, camera } = useThree();
  useEffect(() => {
    if (!when || !onCapture) return;
    const id = requestAnimationFrame(() => {
      gl.render(scene, camera);
      gl.domElement.toBlob((b) => b && onCapture(b), "image/jpeg", 0.85);
    });
    return () => cancelAnimationFrame(id);
  }, [when, gl, scene, camera, onCapture]);
  return null;
}

export default function Viewer3D({ modelUrl, fullModelUrl, pointCloudUrl, info, onCapture, autoCapture,
  tool = "orbit", onPick, onRegion, markers = [], cropBox = null, onBounds }: Props) {
  const [mode, setMode] = useState<DisplayMode>("textured");
  const [camType, setCamType] = useState<CamType>("persp");
  const [view, setView] = useState<View>("iso");
  const [nonce, setNonce] = useState(0);
  const [grid, setGrid] = useState(true);
  const [axes, setAxes] = useState(false);
  const [useFull, setUseFull] = useState(false);
  const [captureTick, setCaptureTick] = useState(0);
  const controls = useRef<any>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const camRef = useRef<THREE.Camera | null>(null);
  const [rect, setRect] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [selection, setSelection] = useState<THREE.BufferGeometry | null>(null);
  const dragging = useRef(false);

  const glb = useGLB(useFull && fullModelUrl ? fullModelUrl : modelUrl);
  const ply = usePLY(mode === "points" ? pointCloudUrl ?? null : null);

  useEffect(() => { if (glb.data) applyMode(glb.data.object, mode === "points" ? "textured" : mode); }, [glb.data, mode]);

  const autoDone = useRef(false);
  useEffect(() => {
    if (autoCapture && glb.data && !autoDone.current) { autoDone.current = true; setTimeout(() => setCaptureTick((t) => t + 1), 300); }
  }, [autoCapture, glb.data]);

  const box = glb.data?.box ?? null;
  useEffect(() => {
    if (box && onBounds) onBounds({ min: box.min.toArray() as [number, number, number], max: box.max.toArray() as [number, number, number] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [box]);
  useEffect(() => { if (tool !== "erase") { setRect(null); setSelection(null); } }, [tool]);
  useEffect(() => () => selection?.dispose(), [selection]);

  /** Faces whose centroid projects inside the rectangle: same rule as the server (edit.py). */
  function computeSelection(r: { x0: number; y0: number; x1: number; y1: number }) {
    const el = wrap.current?.querySelector("canvas");
    const cam = camRef.current;
    if (!el || !cam || !glb.data) return;
    const W = el.clientWidth, H = el.clientHeight;
    const toNdc = (x: number, y: number): [number, number] => [(x / W) * 2 - 1, -((y / H) * 2 - 1)];
    const [ax, ay] = toNdc(Math.min(r.x0, r.x1), Math.min(r.y0, r.y1));
    const [bx, by] = toNdc(Math.max(r.x0, r.x1), Math.max(r.y0, r.y1));
    const polygon: [number, number][] = [[ax, by], [bx, by], [bx, ay], [ax, ay]];
    cam.updateMatrixWorld();
    const vp = new THREE.Matrix4().multiplyMatrices((cam as any).projectionMatrix, cam.matrixWorldInverse);
    const e = vp.elements;
    const out: number[] = [];
    let count = 0;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    glb.data.object.updateMatrixWorld();
    glb.data.object.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const pos = m.geometry.attributes.position;
      const idx = m.geometry.index;
      const nf = idx ? idx.count / 3 : pos.count / 3;
      for (let f = 0; f < nf; f++) {
        const i0 = idx ? idx.getX(3 * f) : 3 * f, i1 = idx ? idx.getX(3 * f + 1) : 3 * f + 1, i2 = idx ? idx.getX(3 * f + 2) : 3 * f + 2;
        a.fromBufferAttribute(pos, i0).applyMatrix4(m.matrixWorld);
        b.fromBufferAttribute(pos, i1).applyMatrix4(m.matrixWorld);
        c.fromBufferAttribute(pos, i2).applyMatrix4(m.matrixWorld);
        const x = (a.x + b.x + c.x) / 3, y = (a.y + b.y + c.y) / 3, z = (a.z + b.z + c.z) / 3;
        const w = e[3] * x + e[7] * y + e[11] * z + e[15];
        if (w <= 1e-9) continue;
        const nx = (e[0] * x + e[4] * y + e[8] * z + e[12]) / w, ny = (e[1] * x + e[5] * y + e[9] * z + e[13]) / w;
        if (nx >= ax && nx <= bx && ny >= by && ny <= ay) {
          count++;
          out.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
        }
      }
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(out, 3));
    setSelection(g);
    onRegion?.(count ? { matrix: Array.from(e), polygon, count } : null);
  }
  const radius = useMemo(() => (box ? box.getBoundingSphere(new THREE.Sphere()).radius : 1), [box]);
  const gridSize = useMemo(() => {
    if (!box) return 10;
    const s = box.getSize(new THREE.Vector3());
    return Math.ceil(Math.max(s.x, s.z) * 1.6) || 10;
  }, [box]);

  const pointsMat = useMemo(() => new THREE.PointsMaterial({ size: radius / 500, vertexColors: true, sizeAttenuation: true }), [radius]);
  const pointsObj = useMemo(() => (ply.geom ? new THREE.Points(ply.geom, pointsMat) : null), [ply.geom, pointsMat]);

  const setPreset = (v: View) => { setView(v); setNonce((n) => n + 1); };
  const fullscreen = useCallback(() => {
    const el = wrap.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen(); else el.requestFullscreen?.();
  }, []);

  const loading = glb.loading || (mode === "points" && ply.loading);
  const progress = glb.loading ? glb.progress : ply.progress;

  return (
    <div ref={wrap} className="relative overflow-hidden rounded-2xl border border-line bg-[#0d0f13]" data-testid="viewer">
      <div className="relative h-[62dvh] min-h-[320px] w-full sm:h-[68vh]">
        {/* Render on demand only (battery / CPU): controls, loads and toolbar changes invalidate. */}
        <Canvas frameloop="demand" dpr={[1, 2]} gl={{ antialias: true, preserveDrawingBuffer: true }} data-testid="viewer-canvas">
          <Invalidate deps={[mode, grid, axes, glb.data, pointsObj, camType, nonce, markers, cropBox, selection]} />
          <color attach="background" args={["#0d0f13"]} />
          {camType === "persp" ? <PerspectiveCamera makeDefault fov={45} /> : <OrthographicCamera makeDefault />}
          <hemisphereLight args={[0xffffff, 0x30343c, 1.1]} />
          <directionalLight position={[3, 5, 4]} intensity={1.6} />
          <directionalLight position={[-4, 2, -3]} intensity={0.5} />
          <CameraGrab target={camRef} />
          {glb.data && mode !== "points" && (
            <primitive object={glb.data.object}
              onClick={(e: any) => { if (tool === "pick" && e.delta < 5) { e.stopPropagation(); onPick?.(e.point.toArray()); } }} />
          )}
          {markers.map((m, i) => (
            <mesh key={i} position={m}><sphereGeometry args={[radius / 120, 16, 16]} /><meshBasicMaterial color={i === 0 ? "#fbbf24" : "#4ade80"} depthTest={false} /></mesh>
          ))}
          {markers.length === 2 && <MeasureLine a={markers[0]} b={markers[1]} />}
          {cropBox && <CropBoxView box={cropBox} />}
          {selection && <mesh geometry={selection} renderOrder={2}><meshBasicMaterial color="#f87171" transparent opacity={0.55} depthTest={false} side={THREE.DoubleSide} /></mesh>}
          {mode === "points" && pointsObj && <primitive object={pointsObj} />}
          {grid && box && <gridHelper args={[gridSize, 20, 0x3a3f4b, 0x22262e]} position={[0, 0, 0]} />}
          {axes && box && <axesHelper args={[radius * 0.6]} />}
          {box && <CameraRig box={box} view={view} camType={camType} nonce={nonce} controls={controls} />}
          <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.12} enabled={tool !== "erase"} />
          <GizmoHelper alignment="bottom-right" margin={[56, 56]}>
            <GizmoViewport axisColors={["#f87171", "#4ade80", "#60a5fa"]} labelColor="#0a0b0e" />
          </GizmoHelper>
          <Capture when={captureTick} onCapture={onCapture} />
        </Canvas>

        {tool === "erase" && (
          <div className="absolute inset-0 cursor-crosshair" data-testid="erase-overlay" style={{ touchAction: "none" }}
            onPointerDown={(e) => { const r = e.currentTarget.getBoundingClientRect(); dragging.current = true; (e.target as HTMLElement).setPointerCapture(e.pointerId); setRect({ x0: e.clientX - r.left, y0: e.clientY - r.top, x1: e.clientX - r.left, y1: e.clientY - r.top }); }}
            onPointerMove={(e) => { if (!dragging.current) return; const r = e.currentTarget.getBoundingClientRect(); setRect((p) => p && { ...p, x1: e.clientX - r.left, y1: e.clientY - r.top }); }}
            onPointerUp={() => { dragging.current = false; if (rect && Math.abs(rect.x1 - rect.x0) > 4 && Math.abs(rect.y1 - rect.y0) > 4) computeSelection(rect); }}>
            {rect && <div className="pointer-events-none absolute border-2 border-danger bg-danger/10"
              style={{ left: Math.min(rect.x0, rect.x1), top: Math.min(rect.y0, rect.y1), width: Math.abs(rect.x1 - rect.x0), height: Math.abs(rect.y1 - rect.y0) }} />}
          </div>
        )}
        {loading && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center">
            <div className="flex items-center gap-3 rounded-xl bg-black/60 px-4 py-2.5 text-sm text-muted backdrop-blur">
              <Spinner />
              {progress != null && progress < 1 ? `Chargement ${Math.round(progress * 100)} %` : "Chargement…"}
            </div>
          </div>
        )}
        {(glb.error || (mode === "points" && ply.error)) && (
          <div className="absolute inset-x-4 top-4 rounded-xl bg-danger/15 px-4 py-2.5 text-sm text-danger">{glb.error ?? ply.error}</div>
        )}

        {/* toolbar */}
        <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
          <Seg value={mode} onChange={(v) => setMode(v as DisplayMode)} options={[
            ["textured", "Texturé"], ["clay", "Sans texture"], ["wireframe", "Filaire"],
            ...(pointCloudUrl ? [["points", "Nuage"] as [string, string]] : []),
          ]} testid="mode" />
        </div>
        <div className="absolute right-3 top-3 flex flex-col items-end gap-1.5">
          <Seg value={camType} onChange={(v) => { setCamType(v as CamType); setNonce((n) => n + 1); }} options={[["persp", "Perspective"], ["ortho", "Ortho"]]} testid="cam" />
          <Seg value={view} onChange={(v) => setPreset(v as View)} options={[["iso", "3D"], ["top", "Dessus"], ["front", "Face"], ["side", "Côté"]]} testid="view" />
        </div>
        <div className="absolute bottom-3 left-3 flex flex-wrap gap-1.5">
          <Toggle on={grid} onClick={() => setGrid(!grid)}>Grille</Toggle>
          <Toggle on={axes} onClick={() => setAxes(!axes)}>Axes</Toggle>
          <button className="rounded-lg bg-black/55 px-2.5 py-1.5 text-xs text-text backdrop-blur hover:bg-black/70" onClick={() => setPreset("iso")}>Recentrer</button>
          <button className="hidden rounded-lg bg-black/55 px-2.5 py-1.5 text-xs text-text backdrop-blur hover:bg-black/70 sm:block" onClick={fullscreen}>Plein écran</button>
          {onCapture && <button className="rounded-lg bg-black/55 px-2.5 py-1.5 text-xs text-text backdrop-blur hover:bg-black/70" onClick={() => setCaptureTick((t) => t + 1)}>Définir la miniature</button>}
        </div>
      </div>
      {info && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-4 py-2.5 text-xs text-muted">
          <span data-testid="viewer-faces">{(useFull ? info.full_faces : info.faces).toLocaleString("fr-FR")} faces affichées</span>
          {info.decimated && !useFull && <span>Aperçu allégé (modèle complet : {info.full_faces.toLocaleString("fr-FR")} faces)</span>}
          {info.decimated && fullModelUrl && (
            <button className="text-accent hover:underline" onClick={() => setUseFull(!useFull)}>
              {useFull ? "Revenir à l'aperçu allégé" : "Charger le modèle complet"}
            </button>
          )}
          {mode === "points" && info.pointcloud_points > 0 && <span>{info.pointcloud_points.toLocaleString("fr-FR")} points</span>}
        </div>
      )}
    </div>
  );
}

function Seg({ value, onChange, options, testid }: { value: string; onChange: (v: string) => void; options: [string, string][]; testid?: string }) {
  return (
    <div className="flex rounded-lg bg-black/55 p-0.5 backdrop-blur" role="group" data-testid={testid}>
      {options.map(([v, l]) => (
        <button key={v} onClick={() => onChange(v)} aria-pressed={value === v}
          className={`rounded-md px-2.5 py-1 text-xs transition-colors ${value === v ? "bg-white/15 text-text" : "text-muted hover:text-text"}`}>{l}</button>
      ))}
    </div>
  );
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} aria-pressed={on}
      className={`rounded-lg px-2.5 py-1.5 text-xs backdrop-blur transition-colors ${on ? "bg-accent-strong/40 text-text" : "bg-black/55 text-muted hover:text-text"}`}>{children}</button>
  );
}

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

interface Props {
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

export default function Viewer3D({ modelUrl, fullModelUrl, pointCloudUrl, info, onCapture, autoCapture }: Props) {
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

  const glb = useGLB(useFull && fullModelUrl ? fullModelUrl : modelUrl);
  const ply = usePLY(mode === "points" ? pointCloudUrl ?? null : null);

  useEffect(() => { if (glb.data) applyMode(glb.data.object, mode === "points" ? "textured" : mode); }, [glb.data, mode]);

  const autoDone = useRef(false);
  useEffect(() => {
    if (autoCapture && glb.data && !autoDone.current) { autoDone.current = true; setTimeout(() => setCaptureTick((t) => t + 1), 300); }
  }, [autoCapture, glb.data]);

  const box = glb.data?.box ?? null;
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
          <Invalidate deps={[mode, grid, axes, glb.data, pointsObj, camType, nonce]} />
          <color attach="background" args={["#0d0f13"]} />
          {camType === "persp" ? <PerspectiveCamera makeDefault fov={45} /> : <OrthographicCamera makeDefault />}
          <hemisphereLight args={[0xffffff, 0x30343c, 1.1]} />
          <directionalLight position={[3, 5, 4]} intensity={1.6} />
          <directionalLight position={[-4, 2, -3]} intensity={0.5} />
          {glb.data && mode !== "points" && <primitive object={glb.data.object} />}
          {mode === "points" && pointsObj && <primitive object={pointsObj} />}
          {grid && box && <gridHelper args={[gridSize, 20, 0x3a3f4b, 0x22262e]} position={[0, 0, 0]} />}
          {axes && box && <axesHelper args={[radius * 0.6]} />}
          {box && <CameraRig box={box} view={view} camType={camType} nonce={nonce} controls={controls} />}
          <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.12} />
          <GizmoHelper alignment="bottom-right" margin={[56, 56]}>
            <GizmoViewport axisColors={["#f87171", "#4ade80", "#60a5fa"]} labelColor="#0a0b0e" />
          </GizmoHelper>
          <Capture when={captureTick} onCapture={onCapture} />
        </Canvas>

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

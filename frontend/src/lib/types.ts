export type ProjectStatus =
  | "empty" | "ready" | "queued" | "processing" | "done" | "failed" | "cancelled" | "interrupted";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
export type StageId = "prepare" | "sfm" | "dense" | "mesh" | "refine" | "texture" | "cleanup" | "export";
export type StageStatus = "pending" | "running" | "finished" | "failed" | "skipped";

export interface Photo {
  name: string;
  size_bytes: number;
  width: number;
  height: number;
  sharpness: number;
  brightness: number;
  warnings: string[];
}

export interface ExportFile {
  file: string;
  size_bytes: number;
  format: string | null;
  textured: boolean | null;
  note: string;
}

export interface Estimate {
  seconds: number;
  based_on_runs: number;
  method: string;
}

export interface Job {
  id: string;
  project_id: string;
  kind: "reconstruct" | "export" | "video";
  params?: Record<string, string>;
  profile: string | null;
  formats: string[];
  resume: boolean;
  status: JobStatus;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  current_stage: StageId | null;
  error: string | null;
  error_stage: StageId | null;
  num_images: number | null;
  duration_s: number | null;
  queue_position: number | null;
  stages: Record<string, { status?: string; duration?: number; message?: string }>;
  events?: JobEvent[];
}

export interface Project {
  id: string;
  name: string;
  created_at: number;
  updated_at: number;
  status: ProjectStatus;
  archived: boolean;
  photo_count: number;
  profile: string | null;
  model_faces: number | null;
  model_size_bytes: number | null;
  has_model: boolean;
  has_thumbnail: boolean;
  thumbnail_3d: boolean;
  last_job_id: string | null;
}

export interface ProjectDetail extends Project {
  photos: Photo[];
  exports: ExportFile[];
  active_job: Job | null;
  estimates: Record<string, Estimate | null>;
  preview: { decimated: boolean; faces: number; full_faces: number; pointcloud_points: number } | null;
}

export interface JobEvent {
  type: "event" | "job_event";
  job_id: string;
  project_id: string;
  stage: StageId;
  status: "started" | "progress" | "log" | "finished" | "failed" | "skipped";
  message: string;
  progress: number | null;
  detail: Record<string, unknown>;
  timestamp: number;
}

export type ServerMessage =
  | (JobEvent & { type: "job_event" })
  | { type: "job_queued" | "job_started" | "job_cancelling"; job_id: string; project_id: string; kind?: string }
  | { type: "job_finished"; job_id: string; project_id: string; status: JobStatus; error?: string | null }
  | { type: "ping" };

export interface SystemInfo {
  version: string;
  data_dir: string;
  reconstruction_available: boolean;
  video_import_available: boolean;
  hardware: {
    os: string; os_version: string; arch: string; cpu_model: string; cpu_cores: number;
    ram_total_mb: number | null; ram_available_mb: number | null; disk_free_mb: number | null;
    gpus: { name: string; vendor: string; cuda_available: boolean }[];
    has_cuda: boolean; notes: string[];
  };
  tools: {
    pycolmap: { version: string | null; available: boolean; note: string | null } | null;
    colmap: { path: string | null; available: boolean };
    openmvs: Record<string, { path: string | null; available: boolean }>;
    openmvs_available: boolean;
    blender: { path: string | null; available: boolean; version: string | null } | null;
    ffmpeg: { path: string | null; available: boolean } | null;
  };
  profiles: { name: string; label: string; description: string }[];
  export_formats: string[];
  stages: { id: StageId; label: string }[];
}

export interface Whoami { role: "desktop" | "device" | "anonymous"; name: string }

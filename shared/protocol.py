"""HTTP contract shared by control plane and any Worker agent.

A Worker written in another language only needs to speak these JSON shapes.
Workers always initiate calls so a home PC behind NAT can still join.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GpuInfo(BaseModel):
    name: str
    memory_mb: int = 0


class WorkerLocks(BaseModel):
    run_open: bool = True
    security_open: bool = False
    admin_open: bool = False


class EnvironmentInfo(BaseModel):
    id: str
    kind: str
    label: str
    executable: str = ""
    version: str = ""
    packages: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)


class ResourceLimits(BaseModel):
    cpu_cores: float | None = None
    memory_mb: int | None = None
    gpu_count: int | None = None


DEFAULT_TIMEOUT_SEC = 8 * 3600


class JobManifest(BaseModel):
    name: str
    runtime: str = Field(description="Image or native runtime, e.g. python:3.12")
    entry: str = Field(description="Command run inside the job directory")
    os: list[str] = Field(default_factory=lambda: ["linux", "windows", "darwin"])
    needs_gpu: bool = False
    timeout_sec: int = DEFAULT_TIMEOUT_SEC


class WorkerRegisterIn(BaseModel):
    name: str
    join_token: str = ""
    username: str = ""
    password: str = ""
    os: str
    arch: str
    runtimes: list[str]
    has_docker: bool
    cpu_cores: int
    memory_mb: int
    gpus: list[GpuInfo] = Field(default_factory=list)
    locks: WorkerLocks = Field(default_factory=WorkerLocks)
    environments: list[EnvironmentInfo] = Field(default_factory=list)


class WorkerRegisterOut(BaseModel):
    worker_id: str
    worker_token: str
    is_platform: bool = False
    label: str = ""


class HeartbeatIn(BaseModel):
    locks: WorkerLocks
    cpu_percent: float
    memory_percent: float
    gpu_percent: list[float] = Field(default_factory=list)
    bytes_sent: int = 0
    bytes_recv: int = 0
    current_job_id: str | None = None
    job_cpu_percent: float = 0
    job_proc_count: int = 0
    environments: list[EnvironmentInfo] | None = None
    ui_kind: str = ""
    ui_port: int = 0


class JobLogIn(BaseModel):
    stream: Literal["stdout", "stderr", "system"]
    line: str


class JobCompleteIn(BaseModel):
    exit_code: int
    error: str | None = None


class JobLease(BaseModel):
    job_id: str
    manifest: JobManifest
    artifact_url: str
    limits: ResourceLimits | None = None
    python_exe: str | None = None


class WorkerCommand(BaseModel):
    id: int
    kind: Literal["set_limits"]
    payload: ResourceLimits


def compatible(manifest: JobManifest, *, os_name: str, runtimes: list[str], has_docker: bool, gpus: list[GpuInfo]) -> bool:
    if manifest.os and os_name not in manifest.os:
        return False
    if manifest.needs_gpu and not gpus:
        return False
    if has_docker or manifest.runtime in runtimes:
        return True
    family = manifest.runtime.split(":")[0]
    return family in runtimes or any(r == family or r.startswith(family + ":") for r in runtimes)

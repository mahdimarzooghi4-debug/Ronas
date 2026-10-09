"""Read-only product discovery API; not an operational marketplace."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from ronas.catalog import ENGINES, Capability, Engine, find_engine

app = FastAPI(
    title="Ronas — Design-Only Product Foundation",
    version="0.1.0",
    description=(
        "Read-only catalog of proposed Domestic and Export capabilities. "
        "Business gates remain OPEN. No trading, AI, payments or export actions."
    ),
)


class CapabilityView(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    title_fa: str
    source_ref: str
    status: str


class EngineView(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    title_fa: str
    source_ref: str
    business_gate: str
    capability_count: int


class EngineDetailView(EngineView):
    capabilities: list[CapabilityView]


def _summary(engine: Engine) -> EngineView:
    return EngineView(
        key=engine.key,
        title_fa=engine.title_fa,
        source_ref=engine.source_ref,
        business_gate=engine.business_gate,
        capability_count=len(engine.capabilities),
    )


def _capability_view(capability: Capability) -> CapabilityView:
    return CapabilityView(
        code=capability.code,
        title_fa=capability.title_fa,
        source_ref=capability.source_ref,
        status=capability.status,
    )


def _engine_or_404(key: str) -> Engine:
    engine = find_engine(key)
    if engine is None:
        raise HTTPException(status_code=404, detail="Unknown engine")
    return engine


@app.get("/healthz", tags=["liveness"])
def liveness() -> dict[str, str]:
    """A live process is NOT Production, security or Business readiness."""
    return {"status": "alive", "scope": "design_only"}


@app.get("/api/v1/product/engines", response_model=list[EngineView], tags=["product-discovery"])
def list_engines() -> list[EngineView]:
    return [_summary(engine) for engine in ENGINES]


@app.get(
    "/api/v1/product/engines/{engine_key}",
    response_model=EngineDetailView,
    tags=["product-discovery"],
)
def get_engine(engine_key: str) -> EngineDetailView:
    engine = _engine_or_404(engine_key)
    return EngineDetailView(
        **_summary(engine).model_dump(),
        capabilities=[_capability_view(capability) for capability in engine.capabilities],
    )


@app.get(
    "/api/v1/product/engines/{engine_key}/capabilities",
    response_model=list[CapabilityView],
    tags=["product-discovery"],
)
def list_capabilities(engine_key: str) -> list[CapabilityView]:
    engine = _engine_or_404(engine_key)
    return [_capability_view(capability) for capability in engine.capabilities]

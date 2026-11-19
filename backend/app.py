"""
AI Engineering Laboratory — Backend skeleton (Stage 1).

Only GET /health is real in Stage 1. Simulation endpoints are defined
here so Stage 2 can implement them against the same contract, but they
explicitly return 501 Not Implemented. Returning a fake result would
violate the project rules, so the skeleton refuses instead of pretending.

Run (Stage 2 preparation only):
    pip install -r requirements.txt
    uvicorn app:app --reload --port 8001
"""

from fastapi import FastAPI

app = FastAPI(title="AI Engineering Laboratory API", version="0.1.0-stage1")


@app.get("/health")
def health():
    """Real in Stage 1. Reports that the API process is up and that
    no solver is available yet."""
    return {"status": "ok", "stage": 1, "solver_available": False}


def _not_implemented(solver: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "stage": 2,
            "solver": solver,
            "detail": "No simulation solver is implemented in Stage 1. "
            "This endpoint is a contract placeholder only.",
        },
    )


@app.post("/api/v1/simulate/beam")
def simulate_beam(payload: dict):
    return _not_implemented("beam")


@app.post("/api/v1/simulate/circuit")
def simulate_circuit(payload: dict):
    return _not_implemented("circuit")


@app.post("/api/v1/simulate/frame")
def simulate_frame(payload: dict):
    return _not_implemented("frame")

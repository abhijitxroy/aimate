"""Account-scoped usage, rates, budget and invoice endpoints."""
from fastapi import Depends, Request


def register(app, store, auth, config_lock):
    @app.get("/api/usage")
    def usage(days: int = 30, offset: int = 0, session=Depends(auth)):
        from app.usage import report
        return report(store, days, offset)

    @app.post("/api/usage/rates")
    async def usage_rate(request: Request, session=Depends(auth)):
        from app.usage import save_rate
        body = await request.json()
        async with config_lock:
            return save_rate(store, body)

    @app.post("/api/usage/budget")
    async def usage_budget(request: Request, session=Depends(auth)):
        from app.usage import save_budget
        async with config_lock:
            return save_budget(store, await request.json())

    @app.post("/api/usage/invoice")
    async def usage_invoice(request: Request, session=Depends(auth)):
        from app.usage import reconcile
        async with config_lock:
            return reconcile(store, await request.json())


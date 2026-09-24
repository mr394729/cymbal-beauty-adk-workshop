"""Firestore job storage with transactional leases and owner-scoped inbox reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class EventStore:
    def __init__(self, project: str, database: str, collection: str = "event_jobs"):
        if database == "(default)" or not database.startswith("cymbal-events-"):
            raise ValueError("Use a dedicated cymbal-events-<namespace>-<env> Firestore database")
        from google.cloud import firestore

        self.client = firestore.Client(project=project, database=database)
        self.jobs = self.client.collection(collection)

    def create(self, job_id: str, job: dict) -> dict:
        from google.api_core.exceptions import AlreadyExists

        ref = self.jobs.document(job_id)
        try:
            ref.create(job, timeout=20, retry=None)
            return job
        except AlreadyExists:
            existing = ref.get(timeout=20, retry=None).to_dict()
            if not existing or any(
                existing.get(k) != job[k] for k in ("owner", "persona", "origin_session_id")
            ):
                raise ValueError("Event request identity conflict") from None
            return existing

    def get(self, job_id: str) -> dict | None:
        return self.jobs.document(job_id).get(timeout=20, retry=None).to_dict()

    def claim(
        self, job_id: str, lease: str, *, now: datetime | None = None
    ) -> tuple[str, dict | None]:
        from google.cloud import firestore

        now = now or datetime.now(UTC)
        ref = self.jobs.document(job_id)

        @firestore.transactional
        def run(transaction):
            job = ref.get(transaction=transaction, timeout=20, retry=None).to_dict()
            if not job:
                return "missing", None
            if job["status"] in {"completed", "failed"}:
                return "finished", job
            if job.get("lease_until") and job["lease_until"] > now:
                return "busy", job
            update = {
                "status": "processing",
                "lease": lease,
                "lease_until": now + timedelta(minutes=6),
                "attempts": int(job.get("attempts", 0)) + 1,
                "updated_at": now,
            }
            transaction.update(ref, update)
            return "claimed", {**job, **update}

        return run(self.client.transaction())

    def update_claim(self, job_id: str, lease: str, values: dict) -> bool:
        from google.cloud import firestore

        ref = self.jobs.document(job_id)

        @firestore.transactional
        def run(transaction):
            job = ref.get(transaction=transaction, timeout=20, retry=None).to_dict()
            if not job or job.get("lease") != lease or job.get("status") != "processing":
                return False
            transaction.update(ref, {**values, "updated_at": datetime.now(UTC)})
            return True

        return run(self.client.transaction())

    def list_owned(self, owner: str, persona: str) -> list[dict]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        docs = (
            self.jobs.where(filter=FieldFilter("owner", "==", owner))
            .order_by("created_at", direction="DESCENDING")
            .limit(30)
            .stream(timeout=20, retry=None)
        )
        rows = [
            {"job_id": d.id, **d.to_dict()} for d in docs if d.to_dict().get("persona") == persona
        ]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:30]

    def mark_read(self, job_id: str, owner: str, persona: str) -> bool:
        from google.cloud import firestore

        ref = self.jobs.document(job_id)

        @firestore.transactional
        def run(transaction):
            job = ref.get(transaction=transaction, timeout=20, retry=None).to_dict()
            if not job or job.get("owner") != owner or job.get("persona") != persona:
                return False
            transaction.update(ref, {"read_at": datetime.now(UTC)})
            return True

        return run(self.client.transaction())

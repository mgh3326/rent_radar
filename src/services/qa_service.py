"""QA service for data quality monitoring and anomaly detection."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import (
    CrawlSourceSnapshot,
    DataQualityIssue,
    fetch_crawl_snapshots,
    fetch_data_quality_issues,
)


class QAService:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def get_snapshots(
        self, lookback_hours: int = 24
    ) -> list[CrawlSourceSnapshot]:
        return await fetch_crawl_snapshots(self._session, lookback_hours=lookback_hours)

    async def get_issues(self, limit: int = 100) -> list[DataQualityIssue]:
        return await fetch_data_quality_issues(self._session, limit=limit)

    async def get_qa_summary(self) -> dict[str, object]:
        snapshots = await self.get_snapshots()
        issues = await self.get_issues()

        blocker_count = sum(1 for i in issues if i.severity == "blocker")
        warning_count = sum(1 for i in issues if i.severity == "warning")

        return {
            "snapshots": [
                {
                    "source": s.source,
                    "table_name": s.table_name,
                    "total_count": s.total_count,
                    "last_24h_count": s.last_24h_count,
                    "last_updated": s.last_updated.isoformat()
                    if s.last_updated
                    else None,
                }
                for s in snapshots
            ],
            "issues": [
                {
                    "id": i.id,
                    "table_name": i.table_name,
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "description": i.description,
                    "record_data": i.record_data,
                }
                for i in issues
            ],
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "total_issues": len(issues),
            "deployment_ready": blocker_count == 0,
        }

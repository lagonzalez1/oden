from typing import List, Any, Optional
from sqlalchemy import text
from Repository.base_repository import PostgresRepository


class CommitteeRepository(PostgresRepository):
    table_name = "committee_membership"
    schema_name = "oden"
    pk_name = "id"

    async def get_committee_membership(self, chamber: Optional[str] = "Sentate"):
        query = text("""
            SELECT
                l.id AS member_id,
                l.first_name,
                l.last_name,
                l.bioguide_id,
                l.chamber,
                l.leadership_role,
                l.party,
                l.state,
                cm.committee_id AS committee_id,
                com.title,
                com.is_subcommittee,
                cm.role,
                com.id
            FROM oden.committee_membership cm
            LEFT JOIN oden.committee com ON cm.committee_id = com.id
            LEFT JOIN oden.legislator l ON l.id = cm.legislator_id
            WHERE com.chamber = :chamber
        """)

        result = await self._session.execute(query, {"chamber": chamber})
        return result.mappings().all()

    async def get_committees_by_bioguide_id(self, bioguide_id: str) -> List[Any]:
        """Return all committees associated with a legislator bioguide_id."""
        query = text("""
            SELECT
                com.id,
                com.committee_id,
                com.title,
                com.chamber,
                com.committee_type,
                com.is_subcommittee,
                com.parent_committee_id,
                com.jurisdiction_source,
                com.tags,
                cm.role,
                cm.rank_in_party,
                cm.is_ex_officio,
                cm.assignment_date,
                l.bioguide_id,
                l.first_name,
                l.last_name,
                l.party,
                l.state
            FROM oden.legislator l
            JOIN oden.committee_membership cm ON cm.legislator_id = l.id
            JOIN oden.committee com ON com.id = cm.committee_id
            WHERE l.bioguide_id = :bioguide_id
            ORDER BY com.is_subcommittee ASC, com.title ASC
        """)
        result = await self._session.execute(query, {"bioguide_id": bioguide_id})
        return result.mappings().all()

    async def merge_membership(
        self,
        committee_id,
        legislator_id,
        role="Member",
        rank_in_party=None,
        is_ex_officio=False,
        assignment_date=None,
    ):
        query = text("""
            INSERT INTO oden.committee_membership (
                committee_id,
                legislator_id,
                role,
                rank_in_party,
                is_ex_officio,
                assignment_date
            )
            VALUES (
                :committee_id,
                :legislator_id,
                :role,
                :rank_in_party,
                :is_ex_officio,
                :assignment_date
            )
            ON CONFLICT (legislator_id, committee_id)
            DO UPDATE SET
                role = EXCLUDED.role,
                rank_in_party = EXCLUDED.rank_in_party,
                is_ex_officio = EXCLUDED.is_ex_officio,
                assignment_date = EXCLUDED.assignment_date
            RETURNING id;
        """)

        result = await self._session.execute(
            query,
            {
                "committee_id": committee_id,
                "legislator_id": legislator_id,
                "role": role,
                "rank_in_party": rank_in_party,
                "is_ex_officio": is_ex_officio,
                "assignment_date": assignment_date,
            },
        )

        return result.scalar_one()   
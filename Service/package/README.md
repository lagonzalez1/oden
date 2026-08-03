# Service Package - External Data Sources

This package contains classes for fetching and parsing data from external government sources.

## CongressLegislatorParser (LegislatorParser.py)

Parses legislator data from GitHub's `unitedstates/congress-legislators` repository.

### Features

- ✅ Fetches JSON from: `https://unitedstates.github.io/congress-legislators/legislators-current.json`
- ✅ Parses all current legislators (House & Senate)
- ✅ Keyed to `oden.legislator` table structure
- ✅ Uses bioguide_id as primary identifier
- ✅ Extracts current term information
- ✅ Determines active status from term end dates
- ✅ Handles both chambers: House and Senate
- ✅ **Does NOT create committee memberships** (handled separately)

### Usage

#### Option 1: Through CommitteeService (Recommended)

```python
from Service.commitee_service import CommitteeService
from Core.SqlAlchemyUnitOfWork import SqlAlchemyUnitOfWork

# Initialize service with unit of work
uow = SqlAlchemyUnitOfWork()
service = CommitteeService(uow)

# Ingest all legislators
result = await service.ingest_legislators_from_github()

print(f"Inserted {result['legislators']} legislators")
print(f"Active: {result['active']}, Inactive: {result['inactive']}")
```

#### Option 2: Direct Parser Usage

```python
from Service.package.LegislatorParser import CongressLegislatorParser

# Initialize parser
parser = CongressLegislatorParser()

# Fetch and parse
legislators = await parser.parse_all()

# Process each legislator
for legislator in legislators:
    print(f"{legislator['first_name']} {legislator['last_name']}")
    print(f"  Chamber: {legislator['chamber']}")
    print(f"  State: {legislator['state']}")
    print(f"  Party: {legislator['party']}")
```

#### Option 3: Via API

```bash
curl -X GET "http://localhost:8000/documents/ingest_legislators_github"
```

### Data Structure

```python
{
    "bioguide_id": "C000127",           # Unique identifier
    "first_name": "Maria",
    "last_name": "Cantwell",
    "party": "Democrat",
    "state": "WA",
    "district": None,                   # House only, e.g., "01", "15"
    "chamber": "senate",                # house or senate
    "official_url": "https://...",
    "is_active": True,                  # Based on term end date
    "prefix": None,                     # Not in GitHub data
    "leadership_role": None,            # Not in GitHub data
    "twitter_handle": None              # Not in GitHub data
}
```

### Important Notes

- **No Committee Memberships**: This parser only creates/updates legislator records. Committee memberships are handled separately.
- **Idempotent**: Uses upsert on bioguide_id, safe to run multiple times.
- **Current Terms Only**: Uses the most recent term from each legislator's history.

---

## CongressCommitteeParser (CommitteeParser.py)

Parses committee data from GitHub's `unitedstates/congress-legislators` repository.

### Features

- ✅ Fetches JSON from: `https://unitedstates.github.io/congress-legislators/committees-current.json`
- ✅ Top-down design: Parent committees → Subcommittees
- ✅ Keyed to `oden.committee` table structure
- ✅ Generates proper committee IDs:
  - Parent: Uses `thomas_id` directly (e.g., `HSAG`, `SSAF`)
  - Subcommittee: Combines parent + sub (e.g., `HSAG15`, `SSAF01`)
- ✅ Handles all three chambers: House, Senate, Joint

### Usage

#### Option 1: Through CommitteeService (Recommended)

```python
from Service.commitee_service import CommitteeService
from Core.SqlAlchemyUnitOfWork import SqlAlchemyUnitOfWork

# Initialize service with unit of work
uow = SqlAlchemyUnitOfWork()
service = CommitteeService(uow)

# Ingest all committees and subcommittees
result = await service.ingest_committee_data_from_github()

print(f"Inserted {result['committees']} committees")
print(f"Inserted {result['subcommittees']} subcommittees")
```

#### Option 2: Direct Parser Usage

```python
from Service.package.Github import CongressCommitteeParser

# Initialize parser
parser = CongressCommitteeParser(congress_num=119)

# Fetch and parse
committees_with_subs = await parser.parse_all()

# Process each committee
for parent_object, subcommittees_raw in committees_with_subs:
    print(f"Committee: {parent_object['title']}")
    print(f"  - ID: {parent_object['committee_id']}")
    print(f"  - Has {len(subcommittees_raw)} subcommittees")
    
    # After inserting parent to DB and getting UUID:
    parent_uuid = "..." # from DB insert
    
    # Build subcommittee objects
    sub_objects = parser.build_subcommittee_objects(
        parent_committee_id=parent_uuid,
        parent_thomas_id=parent_object['committee_id'],
        subcommittees=subcommittees_raw,
        chamber=parent_object['chamber']
    )
    
    # Insert sub_objects to DB
```

### Data Structure

#### Parent Committee Object

```python
{
    "committee_id": "HSAG",              # thomas_id from JSON
    "parent_committee_id": None,         # Always None for parents
    "congress_num": 119,
    "chamber": "house",                  # house, senate, or joint
    "committee_type": "standing",
    "senate_committee_id": None,         # If available in JSON
    "house_committee_id": "AG",          # If available in JSON
    "title": "House Committee on Agriculture",
    "jurisdiction_source": "...",        # Committee jurisdiction text
    "youtube_id": "UCOWh2WJxPywHIaccDWb8Mvg",
    "url": "https://agriculture.house.gov/",
    "office": "1301 LHOB; Washington, DC 20515-6001",
    "is_subcommittee": False,
    "tags": []
}
```

#### Subcommittee Object

```python
{
    "committee_id": "HSAG15",            # parent_thomas_id + sub_thomas_id
    "parent_committee_id": "uuid-...",   # UUID from parent insert
    "congress_num": 119,
    "chamber": "house",
    "committee_type": "standing",
    "senate_committee_id": None,
    "house_committee_id": None,
    "title": "Forestry and Horticulture",
    "jurisdiction_source": None,
    "youtube_id": None,
    "url": None,
    "office": "1301 LHOB; Washington, DC 20515",
    "is_subcommittee": True,             # Always True
    "tags": []
}
```

### Top-Down Design Pattern

The parser ensures proper insertion order:

1. **Fetch & Parse** all committees from JSON
2. **Insert Parent** committee to database
3. **Get Parent UUID** from database response
4. **Build Subcommittee Objects** with `parent_committee_id` set to parent UUID
5. **Insert Subcommittees** to database

This guarantees referential integrity for the `parent_committee_id` foreign key.

### Committee ID Generation

| Type | Source | Example | Formula |
|------|--------|---------|---------|
| Parent (House) | `thomas_id` | `HSAG` | Direct |
| Parent (Senate) | `thomas_id` | `SSAF` | Direct |
| Subcommittee | `parent + sub` | `HSAG15` | `{parent_thomas_id}{sub_thomas_id}` |

### Error Handling

- Invalid committees are logged and skipped (processing continues)
- HTTP errors during fetch are raised (whole operation fails)
- Database transaction errors are caught per-committee (partial success possible)

### Dependencies

- `httpx`: Async HTTP client
- `pydantic`: Data validation
- Unit of Work pattern for database operations

## CongressAPI (Gov.py)

Fetches committee data from the official Congress.gov API.

### Usage

```python
from Service.package.Gov import CongressAPI

api = CongressAPI(api_key="your_key_here")
response = api.get_committee_by_congress_chamber(
    congress=119,
    chamber="house"
)

for committee in response.committees:
    print(f"{committee.name} - {committee.systemCode}")
```

## Data Models (GovModel.py)

Pydantic models for Congress.gov API responses.

- `CommitteeResponse`: Root response model
- `Committee`: Individual committee data
- `CommitteeParent`: Parent committee reference
- `Subcommittees`: Subcommittee list item

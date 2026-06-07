import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import close_mongo_connection, connect_to_mongo
from app.services.registrations import create_registration


async def main() -> None:
    await connect_to_mongo()
    try:
        result = await create_registration(
            transfer_id="test123",
            store_name="Tienda Test",
            phone="51234567",
            password="secret12",
            billing_period="monthly",
        )
        print("OK", result)
    except Exception as exc:
        print("ERROR", type(exc).__name__, exc)
        raise
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())

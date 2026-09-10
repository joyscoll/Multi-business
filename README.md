# MultiBusiness v1 — Vehicle Catalog Upgrade

Flask/Gunicorn multi-business build. This upgrade deepens the Vehicles world without mixing it with Hotels or Property.

## Vehicle catalogue
- 150 distinct make/model records.
- 94 vehicle types.
- 404 searchable quick-filter choices covering types, makes, models, years, fuel, transmission, location, features, colour, drivetrain, ownership, service, engine size, seats, doors and condition.
- 150 local image assets, each generated from the same make/model record and filename. Demo imagery is deterministic and self-labelled to avoid random-image/name mismatches.
- Existing records are preserved; on the first vehicle seed, missing demo records are added until the full 150-record set is present.

## Customer experience
- Vehicle cards show make + model explicitly.
- Detail pages repeat make/model/type/year as a bound identity block.
- QR is available from public pages for business/listing sharing.
- Search and quick filters operate within the selected business world only.

## Run
`pip install -r requirements.txt`
`gunicorn app:app`

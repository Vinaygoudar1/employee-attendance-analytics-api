# Employee Attendance & Analytics API

HROne Software Engineer Trainee technical assignment.

## 1. Project Overview

This project is an Employee Attendance & Analytics API developed as part of the HROne Software Engineer Trainee technical assignment. It provides REST APIs to manage employees, record attendance, correct attendance records, and generate attendance analytics using Python, FastAPI, and MongoDB.

## 2. Technologies Used

- **Python 3.12** — application logic and business rules.
- **FastAPI** — REST API development and Swagger documentation.
- **MongoDB** — employee and attendance data storage.
- **PyMongo** — database connectivity, queries, updates, and aggregation pipelines.
- **Pydantic** — request data validation.
- **Uvicorn** — local application server.
- **python-dotenv** — loading environment variables during local development.

## 3. Features Implemented

### Employee Management
- Create employee records with employee code, name, email, department, shift timings, and joining date.
- List employees with pagination and department filtering.
- Prevent duplicate employee codes using a unique MongoDB index.

### Attendance Management
- Record employee punch-in and punch-out timestamps.
- Calculate late arrival minutes, working hours, overtime, and half-day status.
- Prevent duplicate attendance entries for the same employee and attendance date.
- Validate punch-out times and attendance intervals.
- Retrieve attendance records with employee, date, and status filters and pagination.
- Regularize attendance records using a PATCH endpoint.
- Maintain an audit history for manual attendance corrections, including the correction time, person making the change, reason, and changed values.

### Attendance Analytics
- Generate monthly employee attendance summaries.
- Generate department-level attendance summaries.
- Provide a leaderboard ranking employees by total late minutes.
- Generate daily department attendance trends, including dates without attendance records, with a seven-day moving average.

### MongoDB Explain Endpoint
- Implement an administrative explain endpoint for the attendance list, employee monthly analytics, department summary, late leaderboard, and department trend.
- Use MongoDB execution statistics to inspect query plans and index usage.
- Add indexes to support employee lookups, attendance date filtering, and employee-date queries.

## 4. Project Structure

```text
candidate_kit/
├── app/
│   └── main.py
├── DATA_MODEL.md
├── DECISIONS.md
├── REVIEW.md
├── openapi.yaml
├── requirements.txt
├── README.md
└── .gitignore
```

## 5. Configuration and Setup

### Prerequisites

- Python 3.11 or newer
- MongoDB 6.0 or newer, either locally or through MongoDB Atlas
- Git

### Environment Variables

Configure the following variables in a local `.env` file or your environment:

```text
MONGO_URI=your_mongodb_connection_string
MONGO_DB=your_database_name
```

Keep the `.env` file and all database credentials private. Do not commit credentials to GitHub.

### Install Dependencies

From the project directory, run:

```bash
pip install -r requirements.txt
```

### Start the Application

Run:

```bash
uvicorn app.main:app --port 8000
```

Open the following URLs in your browser:

- Health check: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

## 6. API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check application and database connectivity |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees |
| POST | `/attendance/punch-in` | Record punch-in |
| POST | `/attendance/punch-out` | Record punch-out |
| GET | `/attendance` | List attendance records |
| PATCH | `/attendance/{emp_code}/{date}` | Correct an attendance record |
| GET | `/analytics/employees/{emp_code}/monthly` | Retrieve employee monthly analytics |
| GET | `/analytics/departments/summary` | Retrieve department summaries |
| GET | `/analytics/leaderboard/late` | Retrieve the late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Retrieve daily department trends |
| GET | `/admin/explain/{endpoint}` | Inspect MongoDB query execution plans |

## 7. Testing Performed

The application was run locally using Uvicorn and tested through the Swagger UI.

The following checks were performed:

- Health endpoint returned `200 OK`.
- Employee creation succeeded; duplicate employee codes returned `409 Conflict`.
- Request validation was checked using an invalid employee request.
- Punch-in and punch-out requests were tested.
- A punch-out test confirmed 9.5 working hours and 30 overtime minutes for a normal shift.
- Attendance listing returned the expected attendance record.
- Attendance regularization successfully changed a status and recorded the correction in audit history.
- Employee monthly analytics returned attendance metrics.
- Department summary, late leaderboard, and department trend endpoints returned successful responses.
- Explain requests for attendance listing, employee monthly analytics, department summary, late leaderboard, and department trend returned execution plans using indexes for the tested queries.
- Python compilation was checked using `python -m compileall app`.

These were manual development checks with the available test data, not a complete automated test suite.

## 8. Documentation and Design Decisions

- `openapi.yaml` describes the API contract.
- `DATA_MODEL.md` documents the data model.
- `DECISIONS.md` records implementation and design decisions.
- `REVIEW.md` contains the review of the starter code and identified issues.

## 9. Remaining Validation

The following items still require further validation before the implementation can be considered fully verified against the assignment:

- Run comprehensive automated tests against the full API contract.
- Verify overnight-shift and timestamp-boundary calculations.
- Stress-test simultaneous punch-in, punch-out, and regularization requests.
- Validate all analytics calculations against controlled test data.
- Verify explain plans on the assignment-scale dataset of approximately 100,000 attendance records and check for collection scans.
- Confirm every explain branch uses the same query or aggregation, filters, sorting, and pagination as its corresponding endpoint.
- Verify the final repository contains every required submission file and no secrets.

## 10. Summary

This project implements the core employee attendance workflows and analytics endpoints using FastAPI and MongoDB. Development included request validation, database indexing, attendance calculations, audit history, aggregation pipelines, and query-plan inspection. Further edge-case, concurrency, and large-dataset testing is needed to establish full compliance with the assignment requirements.
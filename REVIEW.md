# REVIEW\.md

## Issues Found and Fixed

Timestamp handling: Invalid timestamps could cause errors. I added validation and corrected timestamp conversion.

Punch-in date: Overnight shifts could have the wrong attendance date. I corrected the date calculation.

Late minutes: The 10-minute grace period was not handled correctly. I corrected the late-minute calculation.

Overtime: Overtime needed to consider the shift end time, including overnight shifts. I corrected the calculation.

Duplicate punch-in: Multiple requests could create duplicate attendance records. I added a unique index and conflict handling.

Duplicate punch-out: Multiple requests could close the same record. I added a conditional database update.

Attendance history: Previous correction history must be preserved. I updated the code to append history safely and record actual changes.

Work hours: Work hours and half-day status must follow the assignment rules. I corrected the calculations and rounding.

Monthly analytics: Working days must account for weekends and joining dates. I used a MongoDB aggregation pipeline.

Department summary: Employees without attendance records must still be included in the headcount. I corrected the aggregation.

Late leaderboard: Employees with the same rank at the limit must not be excluded. I corrected the ranking logic to preserve ties.

Department trend: Dates without attendance records and weekends must also appear. I updated the pipeline to include missing dates and calculate moving averages.

Explain endpoint: Query performance must be checked using execution statistics. I added execution plans for the supported queries.

## Checks That Were Not Defects

I checked the UTC conversion and rounding helpers. Their core logic was suitable for handling timestamps and rounding values according to the assignment rules. I also checked the late-minute calculation to ensure the 10-minute grace period was handled correctly.
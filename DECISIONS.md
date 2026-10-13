# DECISIONS.md

## 1. Indexes

I added indexes to make the API faster and prevent duplicate records. The unique index on `employees.emp_code` ensures that each employee has a unique code. I also added indexes on department and joining date to help with employee filtering and department analytics. For attendance, the unique index on `emp_code` and `date` prevents an employee from having multiple attendance records for the same day. Another index on date and employee code helps with attendance filtering and sorting.

## 2. Punch-in Race

If two punch-in requests arrive at almost the same time for the same employee, the unique attendance index prevents both from creating separate records. One request succeeds, while the other should return a conflict response.

## 3. Ties

For the late leaderboard, I used standard competition ranking. For example, if two employees share rank 2, the next employee receives rank 4. Employees with the same ranking are ordered by employee code. Tied employees at the limit are included instead of cutting off the results arbitrarily.

## 4. Headcount

I start the department summary with employee records and then look up their attendance. This way, employees who have no attendance logs are still counted if they joined by the end of the reporting period.

## 5. Scaling to 100x Data

If the data grows 100 times larger, I would first test the API with a larger dataset and review MongoDB execution statistics. I would then focus on the slowest queries and optimize them before making further infrastructure changes.
# UI Views

Brief description of UI views

* Machines View: table of machine-id, hardware, OS, Up For, Status (OK, ...), last message, commit, test suite, logs, cancel button.
* Repos View: table of repos and primary test branch
* Repo View: table of branches and test-flag
* Branch/Commit View: table of commit, test-flag, results summary, commit summary, commit diff, commit info (log), clear-test-results button
* Commit Summary View [we might not need this]: table where environments are columns and rows are suites (e.g., matlab, python, ...)
* Commit Tests View:  rows are env-suite-test triplets, columns are commits, cells are test run summary. Click on commit hash to transition to that commit.
* Single Test View: x-axis are commits, y-axis are various metrics: #runs, %fails, runtime, perf-metric if perf-test  
* Suites View: table of suite, hash, env, prioritized, status, runs, target runs, #tests, #failures, logs
* TestDefinitions: show the testDefinitions file for the given commit
* TestList per suite (produced by running the test listing script)

# testlooper

Testlooper is a CI platform for testing git repositories. An arbitrary number and selection of
a repo's tests can be run for any commit in the repo, and branches can be automatically tested, to
monitor and investigate hard-to-find flakey tests.

Testlooper is:

1. language agnostic: anything that can be run in a docker container can be tested. Both the listing
   and running of tests is done via a specified bash command.
2. configurable: the user must decide how to generate the test plan, and what build steps testlooper
   should perform.



## Usage
To use testlooper locally, see `run_local.py` for an example. Testlooper is provided with ports for
HTTP and ODB (`object_database`, used for backend storage, see [here](https://github.com/APrioriInvestments/object_database)),
and a path to a local git repository and a testlooper config file. When run, it will scan the repo
to a given commit depth and then watch for any pushed changes, and provide a UI on the specified
port to run and view tests. The git repo itself must have a post-receive hook capable of POSTing to
the port testlooper is using to track git changes.


For the details of the config file, see [here](./docs/specs/Repo_Configuration_Spec.md).


## Necessary files:

- config
- test\_plan
- test plan generation script.
- run and list test scripts.


## Limitations
- Currently only runs locally.
- Doesn't yet support direct Github/Gitlab tracking
- No support for AWS AMI.
- UI requires a linear branch history (no merges, only rebases).

## TL internals

Testlooper state is tracked using object\_database objects. There are three key schema:
1. repo\_schema: Describes Git objects (Repo, Commit, Branch, etc)
2. test\_schema: Describes the configuration of tests for a commit, suites, individual tests,
    and results.
3. engine\_schema: Describes the tasks being performed by testlooper and the results thereof.


State changes in testlooper come from two places:

1. Changes to the Git repo. When the Git repo changes, the git watcher service receives a POST
   request, and generates repo ODB objects. It also creates GenerateTestConfigTask and 
   BranchDesiredTesting/CommitDesiredTesting objects, which are picked up and propagated to 
   test new commits as required.
2. Changes to the required testing, from the UI. The number of test runs, and the tests on which to
   run, can be changed for any commit in the UI. This will cause changes to the CommitDesiredTesting
   which will result in new TestRunTasks, which get picked up by the engine and used to (re)run the tests.

Once the state has changed, Testlooper uses object\_database Reactors to propagate the changes
forward. See [here](./docs/reactors.md) for a state diagram and summary of testlooper's Reactors.
For more information on Reactors, see [here](https://github.com/APrioriInvestments/object_database/blob/dev/object_database/reactor.py).

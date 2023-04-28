# Engine

It has access to the artifact store.

It can handle these engine events:
    TestPlanGenerationTask -> TestPlanGenerationResult

    BuildDockerImageTask -> BuildDockerImageResult

    TestSuiteGenerationTask -> TestSuiteGenerationResult

    TestRunTask

We may be able to implement a queue abstraction using ODB objects as long as the queue is small
with chunky object


## Local Engine

Implements the Testlooper Backend by executing the tasks locally in subprocesses.
It is limited to docker tasks (it cannot run AWS AMIs), requires Docker to be installed
and having access to /var/run/docker.sock, and can only run subprocesses on the local box.
It will limit pending subprocesses to a given number that defaults to a multiple of the number of cores on that box.


## AWS Engine

Implements the Testlooper Backend by executing the tasks on AWS EC2 instances running
TestlooperWorker services. It consists of:
  - a scheduler service that runs locally and organizes tasks into queues (mainly the
    TestRunTasks; the others will probably go into a couple of queues based on if we
    want an AMI or a docker image)

  - an instance-manager service that runs locally and orchestrates how many EC2 instances
    and of which kind are booted at any point in time

  - multiple worker-services per EC2 instance (one per core?) who will be assigned to
    one or more work-queues by the scheduler service

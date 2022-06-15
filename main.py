import argparse

from test_looper.runner import TestRunner

parser = argparse.ArgumentParser(description="Test Looper")

# general args
parser.add_argument('--dockerfile', help='Path to dockerfile',
                    default="./Dockerfile", type=str)

# GIT specific arguments
gitargs = parser.add_argument_group('GIT')
gitargs.add_argument('--git-username')
gitargs.add_argument('--git-token')
gitargs.add_argument('--add-repo')

def main(args):
    runner = TestRunner()
    runner.setup()
    runner.run()

if __name__ == '__main__':
    args = parser.parse_args()
    main(args)

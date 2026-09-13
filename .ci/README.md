# Project verification

Run `sh .ci/check.sh` from a clean checkout. Python installs should run inside a virtual environment. The selected checks are also defined in `.github/workflows/project-checks.yml` and run on pushes and pull requests. These checks do not deploy the project or configure provider credentials.

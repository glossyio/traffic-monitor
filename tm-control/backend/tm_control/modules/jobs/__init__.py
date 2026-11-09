"""Root jobs' status and log, which the UI polls after an action returns a job id."""

from tm_control.modules import Module
from tm_control.modules.jobs.router import router

module = Module("jobs", router)

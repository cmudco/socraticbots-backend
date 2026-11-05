"""Sentry setup and configuration."""

import sentry_sdk
from django.core.exceptions import DisallowedHost
from sentry_sdk.integrations.django import DjangoIntegration


def init_sentry(*, dsn, environment="development", traces_sample_rate=0.1):
    """
    Initializes Sentry.

    Args:
        dsn (str): the Sentry DSN key
        environment (str): deployment this process belongs to (development,
            staging, production). Without it every server reports as
            "production" and the environment filter is useless.
        traces_sample_rate (float): fraction of requests traced for performance.
    """
    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        include_local_variables=False,
        # Raised when a scanner requests the server by raw IP instead of a
        # configured hostname. Django is rejecting the request correctly, so
        # the event carries no signal.
        ignore_errors=[DisallowedHost],
    )

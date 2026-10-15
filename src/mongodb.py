import os
from typing import Any, Dict

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import (
    ConfigurationError,
    OperationFailure,
    ServerSelectionTimeoutError,
)

load_dotenv(override=True)


DEFAULT_DATABASE = "routesense"
DEFAULT_COLLECTION = "delivery_events"


EMPTY_FAILURE_COLUMNS = [
    "_id",
    "failure_count",
    "average_delay",
    "maximum_delay",
]


EMPTY_HOURLY_COLUMNS = [
    "_id",
    "total_attempts",
    "failed_attempts",
    "failure_rate",
]


EMPTY_HOTSPOT_COLUMNS = [
    "_id",
    "total_orders",
    "failed_orders",
    "repeat_failure_orders",
    "failure_rate",
    "repeat_failure_rate",
    "hotspot_score",
]


def _get_atlas_uri() -> str:

    uri = os.getenv(
        "ROUTESENSE_ATLAS_URI",
        ""
    ).strip()

    if not uri:

        raise RuntimeError(
            "ROUTESENSE_ATLAS_URI is not configured."
        )

    if not uri.startswith(
        (
            "mongodb://",
            "mongodb+srv://"
        )
    ):

        raise RuntimeError(
            "ROUTESENSE_ATLAS_URI must be a valid "
            "MongoDB connection URI."
        )

    if (
        "localhost" in uri.lower()
        or "127.0.0.1" in uri
    ):

        raise RuntimeError(
            "ROUTESENSE_ATLAS_URI points to localhost. "
            "Use the MongoDB Atlas cluster URI."
        )

    return uri


def _get_atlas_credentials() -> tuple[str, str]:

    username = os.getenv(
        "ROUTESENSE_ATLAS_USER",
        ""
    ).strip()

    password = os.getenv(
        "ROUTESENSE_ATLAS_PASSWORD",
        ""
    )

    if not username:

        raise RuntimeError(
            "ROUTESENSE_ATLAS_USER is not configured."
        )

    if not password:

        raise RuntimeError(
            "ROUTESENSE_ATLAS_PASSWORD is not configured."
        )

    return username, password


def _remove_uri_credentials(uri: str) -> str:
    """
    Remove username/password from the URI.

    This prevents an old password embedded inside
    ROUTESENSE_ATLAS_URI from overriding the current
    Railway password variable.
    """

    scheme, remainder = uri.split(
        "://",
        1
    )

    if "@" in remainder:

        remainder = remainder.split(
            "@",
            1
        )[1]

    return (
        f"{scheme}://{remainder}"
    )


def get_collection() -> Collection:
    """
    Connect to MongoDB Atlas and return:

        routesense.delivery_events
    """

    uri = _get_atlas_uri()

    username, password = (
        _get_atlas_credentials()
    )

    database_name = os.getenv(
        "ROUTESENSE_MONGODB_DATABASE",
        DEFAULT_DATABASE
    ).strip()

    collection_name = os.getenv(
        "ROUTESENSE_MONGODB_COLLECTION",
        DEFAULT_COLLECTION
    ).strip()

    if not database_name:

        database_name = DEFAULT_DATABASE

    if not collection_name:

        collection_name = DEFAULT_COLLECTION

    # Strip credentials from the URI and authenticate
    # explicitly using Railway's separate variables.
    clean_uri = _remove_uri_credentials(
        uri
    )

    try:

        client = MongoClient(
            clean_uri,
            username=username,
            password=password,
            authSource="admin",
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=20000,
            retryWrites=True
        )

        client.admin.command(
            "ping"
        )

    except OperationFailure as exc:

        raise RuntimeError(
            "MongoDB Atlas authentication failed. "
            "Check ROUTESENSE_ATLAS_USER and "
            "ROUTESENSE_ATLAS_PASSWORD."
        ) from exc

    except ServerSelectionTimeoutError as exc:

        raise RuntimeError(
            "MongoDB Atlas server could not be reached. "
            "Check the Atlas cluster status, URI, DNS, "
            "and Atlas Network Access."
        ) from exc

    except ConfigurationError as exc:

        raise RuntimeError(
            "MongoDB Atlas URI configuration is invalid."
        ) from exc

    except Exception as exc:

        raise RuntimeError(
            "MongoDB Atlas connection failed."
        ) from exc

    return client[
        database_name
    ][
        collection_name
    ]


def get_kpis(
    collection: Collection
) -> Dict[str, Any]:
    """
    Calculate KPIs using actual delivery-attempt
    documents rather than counting unrelated event types.
    """

    attempt_filter = {
        "attempt.status": {
            "$in": [
                "Failed",
                "Delivered"
            ]
        }
    }

    total_attempts = (
        collection.count_documents(
            attempt_filter
        )
    )

    failed_attempts = (
        collection.count_documents(
            {
                "attempt.status": "Failed"
            }
        )
    )

    delivered_attempts = (
        collection.count_documents(
            {
                "attempt.status": "Delivered"
            }
        )
    )

    unique_events = len(
        collection.distinct(
            "event_id"
        )
    )

    failure_rate = (

        failed_attempts
        / total_attempts
        * 100

        if total_attempts

        else 0.0
    )

    return {
        "total_attempts":
            total_attempts,

        "failed_attempts":
            failed_attempts,

        "delivered_attempts":
            delivered_attempts,

        "unique_events":
            unique_events,

        "failure_rate":
            failure_rate
    }


def get_failure_summary(
    collection: Collection
) -> pd.DataFrame:

    pipeline = [

        {
            "$match": {
                "attempt.status": "Failed"
            }
        },

        {
            "$group": {

                "_id": {
                    "$ifNull": [
                        "$attempt.failure_reason",
                        "Unknown"
                    ]
                },

                "failure_count": {
                    "$sum": 1
                },

                "average_delay": {
                    "$avg":
                        "$attempt.delay_minutes"
                },

                "maximum_delay": {
                    "$max":
                        "$attempt.delay_minutes"
                }
            }
        },

        {
            "$sort": {
                "failure_count": -1
            }
        }
    ]

    results = list(
        collection.aggregate(
            pipeline
        )
    )

    if not results:

        return pd.DataFrame(
            columns=EMPTY_FAILURE_COLUMNS
        )

    return pd.DataFrame(
        results
    )


def get_hourly_summary(
    collection: Collection
) -> pd.DataFrame:

    pipeline = [

        {
            "$match": {
                "attempt.status": {
                    "$in": [
                        "Failed",
                        "Delivered"
                    ]
                }
            }
        },

        {
            "$set": {

                "event_time": {

                    "$convert": {

                        "input":
                            "$timestamp",

                        "to":
                            "date",

                        "onError":
                            None,

                        "onNull":
                            None
                    }
                }
            }
        },

        {
            "$match": {
                "event_time": {
                    "$ne": None
                }
            }
        },

        {
            "$group": {

                "_id": {
                    "$hour":
                        "$event_time"
                },

                "total_attempts": {
                    "$sum": 1
                },

                "failed_attempts": {

                    "$sum": {

                        "$cond": [

                            {
                                "$eq": [
                                    "$attempt.status",
                                    "Failed"
                                ]
                            },

                            1,

                            0
                        ]
                    }
                }
            }
        },

        {
            "$set": {

                "failure_rate": {

                    "$cond": [

                        {
                            "$gt": [
                                "$total_attempts",
                                0
                            ]
                        },

                        {
                            "$multiply": [

                                {
                                    "$divide": [
                                        "$failed_attempts",
                                        "$total_attempts"
                                    ]
                                },

                                100
                            ]
                        },

                        0
                    ]
                }
            }
        },

        {
            "$sort": {
                "_id": 1
            }
        }
    ]

    results = list(
        collection.aggregate(
            pipeline
        )
    )

    if not results:

        return pd.DataFrame(
            columns=EMPTY_HOURLY_COLUMNS
        )

    return pd.DataFrame(
        results
    )


def get_route_hotspots(
    collection: Collection
) -> pd.DataFrame:

    pipeline = [

        {
            "$match": {

                "attempt.status": {
                    "$in": [
                        "Failed",
                        "Delivered"
                    ]
                },

                "route.route_id": {
                    "$ne": None
                },

                "order.order_id": {
                    "$ne": None
                }
            }
        },

        # One row per route + order.
        {
            "$group": {

                "_id": {

                    "route_id":
                        "$route.route_id",

                    "order_id":
                        "$order.order_id"
                },

                "failed": {

                    "$max": {

                        "$cond": [

                            {
                                "$eq": [
                                    "$attempt.status",
                                    "Failed"
                                ]
                            },

                            1,

                            0
                        ]
                    }
                },

                "failed_attempts": {

                    "$sum": {

                        "$cond": [

                            {
                                "$eq": [
                                    "$attempt.status",
                                    "Failed"
                                ]
                            },

                            1,

                            0
                        ]
                    }
                }
            }
        },

        # One row per route.
        {
            "$group": {

                "_id":
                    "$_id.route_id",

                "total_orders": {
                    "$sum": 1
                },

                "failed_orders": {
                    "$sum": "$failed"
                },

                "repeat_failure_orders": {

                    "$sum": {

                        "$cond": [

                            {
                                "$gt": [
                                    "$failed_attempts",
                                    1
                                ]
                            },

                            1,

                            0
                        ]
                    }
                }
            }
        },

        {
            "$match": {

                "total_orders": {
                    "$gte": 100
                }
            }
        },

        {
            "$set": {

                "failure_rate": {

                    "$cond": [

                        {
                            "$gt": [
                                "$total_orders",
                                0
                            ]
                        },

                        {
                            "$multiply": [

                                {
                                    "$divide": [
                                        "$failed_orders",
                                        "$total_orders"
                                    ]
                                },

                                100
                            ]
                        },

                        0
                    ]
                },

                "repeat_failure_rate": {

                    "$cond": [

                        {
                            "$gt": [
                                "$total_orders",
                                0
                            ]
                        },

                        {
                            "$multiply": [

                                {
                                    "$divide": [
                                        "$repeat_failure_orders",
                                        "$total_orders"
                                    ]
                                },

                                100
                            ]
                        },

                        0
                    ]
                }
            }
        },

        {
            "$sort": {
                "failure_rate": -1
            }
        }
    ]

    results = list(
        collection.aggregate(
            pipeline
        )
    )

    if not results:

        return pd.DataFrame(
            columns=EMPTY_HOTSPOT_COLUMNS
        )

    df = pd.DataFrame(
        results
    )

    # Calculate normalized hotspot score safely
    # in Python instead of depending on advanced
    # MongoDB window-function behavior.

    max_failure_rate = (
        df["failure_rate"].max()
        if not df.empty
        else 0
    )

    max_repeat_rate = (
        df["repeat_failure_rate"].max()
        if not df.empty
        else 0
    )

    max_orders = (
        df["total_orders"].max()
        if not df.empty
        else 0
    )

    failure_component = (
        df["failure_rate"]
        / max_failure_rate
        * 60
        if max_failure_rate > 0
        else 0
    )

    repeat_component = (
        df["repeat_failure_rate"]
        / max_repeat_rate
        * 30
        if max_repeat_rate > 0
        else 0
    )

    volume_component = (
        df["total_orders"]
        / max_orders
        * 10
        if max_orders > 0
        else 0
    )

    df["hotspot_score"] = (
        failure_component
        + repeat_component
        + volume_component
    )

    return df[
        [
            "_id",
            "total_orders",
            "failed_orders",
            "repeat_failure_orders",
            "failure_rate",
            "repeat_failure_rate",
            "hotspot_score"
        ]
    ]
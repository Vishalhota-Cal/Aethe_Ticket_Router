"""
domain/enums.py

Defines the fixed, allowed values for a ticket's category, priority, and
assigned team. Nothing else in the codebase is allowed to invent a new
value on the fly -- if it is not listed here, it gets rejected before it
ever reaches an agent, an API response, or the database.
"""

from enum import Enum


class Category(str, Enum):
    """The fixed list of ticket categories the system understands."""

    TECHNICAL = "Technical"
    BILLING = "Billing"
    ACCOUNT = "Account"
    SECURITY = "Security"
    GENERAL = "General"


class Priority(str, Enum):
    """The fixed list of urgency levels a ticket can be assigned."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class Team(str, Enum):
    """The fixed list of support teams a ticket can be routed to."""

    IT_SUPPORT = "IT Support"
    BILLING_TEAM = "Billing Team"
    SECURITY_TEAM = "Security Team"
    ACCOUNT_MANAGEMENT = "Account Management"
    GENERAL_SUPPORT = "General Support"


class Sentiment(str, Enum):
    """The detected emotional tone of the ticket's text -- used to
    catch the 'angry customer' edge case explicitly, rather than
    hoping priority alone reflects it.
    """

    ANGRY = "Angry"
    FRUSTRATED = "Frustrated"
    NEUTRAL = "Neutral"
    POSITIVE = "Positive"


class TicketStatus(str, Enum):
    """The lifecycle stage of a ticket after it's been routed. This is
    set and moved forward by an admin/agent working the ticket -- it is
    completely separate from the AI's routing decision (category,
    priority, team). A ticket starts at NEW if it couldn't be
    auto-assigned to anyone yet, or IN_PROGRESS if it was immediately
    handed to an employee -- an assigned ticket shouldn't sit in the
    "not yet picked up" column.
    """

    NEW = "New"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"
    CLOSED = "Closed"
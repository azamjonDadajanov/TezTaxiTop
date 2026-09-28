"""Matching application: deterministic, explainable trip <-> request matching.

The matcher is intentionally **not** machine learning and **not** random:

1. **Hard filters** (database level) remove every trip that cannot work at all:
   not bookable, no free seats, departure outside the requested window, price
   above the passenger budget, driver not verified / vehicle not verified /
   no active subscription, same driver, already ordered by this passenger.
2. **Scoring** turns the remaining candidates into a 0..100 score built from
   independent, documented components.
3. **Deterministic tie-breaking** (score desc, then departure asc, price asc,
   rating desc, trip id asc) guarantees that the same input always produces the
   same ordering - which is what makes the feature testable and explainable to
   a driver ("why is this trip ranked first?").

``TripMatch`` stores the score and its components so the driver can see the
reasoning, and so the ranking can be audited afterwards.
"""

default_app_config = "apps.matching.apps.MatchingConfig"

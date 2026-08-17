"""Seed realistic demo content for the local dev database.

The dev database has accumulated ~1300 published courses from test runs
("Catalogue Test Course <hex>"), which makes the catalogue undemoable.
This script adds a small set of *real* programmes — full metadata,
modules, lessons, outcomes, pricing and tenant assignment — so the
catalogue, programme detail, wizard and dashboard all have honest
content to show.

Idempotent: re-running updates the same courses (matched on slug) rather
than creating duplicates. It never deletes anything, and it never
touches orders, payments or entitlements.

    apps/api/.venv/Scripts/python.exe scripts/seed_demo_content.py

Nothing here runs in production: it refuses unless ENVIRONMENT is local.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import get_settings
from src.core.db import get_sessionmaker, init_engine, set_tenant
from src.core.ids import uuid7
from src.models.article import Article
from src.models.commerce import Price, Product
from src.models.course import Course, CourseTenantAssignment, Lesson, Module
from src.models.credential import CertificateTemplate
from src.models.podcast import PodcastEpisode

# (slug, title, summary, topic, level, format, workshop, colour, price, outcomes, modules)
PROGRAMMES: list[dict] = [
    {
        "slug": "leading-through-ambiguity",
        "title": "Leading Through Ambiguity",
        "summary": (
            "For senior managers who have to commit to a direction before the information is "
            "complete — and then hold a team steady while it changes."
        ),
        "topic": "Leadership",
        "level": "executive",
        "format": "blended",
        "workshop": True,
        "colour": "#8E151C",
        "price": Decimal("2450.00"),
        "outcomes": [
            "Make and communicate a decision when the data is incomplete, without "
            "pretending it isn't",
            "Give a team a stable operating rhythm while the direction is still moving",
            "Run a reversible-decision review that does not turn into a blame exercise",
            "Recognise when ambiguity is genuine and when it is avoidance",
        ],
        "modules": [
            (
                "Naming the ambiguity",
                [
                    ("What ambiguity actually costs a team", "public"),
                    ("Uncertainty, risk and avoidance", "paid"),
                ],
            ),
            (
                "Deciding without complete information",
                [
                    ("Reversible and irreversible decisions", "paid"),
                    ("Setting a decision deadline", "paid"),
                    ("Communicating a provisional direction", "paid"),
                ],
            ),
            ("Holding the team through the change", [("The operating rhythm", "paid")]),
        ],
    },
    {
        "slug": "difficult-conversations-at-board-level",
        "title": "Difficult Conversations at Board Level",
        "summary": (
            "The conversations that decide whether a board functions — raised early, in the room, "
            "without turning a disagreement into a personality problem."
        ),
        "topic": "Communication",
        "level": "executive",
        "format": "self_paced",
        "workshop": False,
        "colour": "#3E4A3C",
        "price": Decimal("1850.00"),
        "outcomes": [
            "Raise a concern in the room rather than eleven days later in a corridor",
            "Separate the disagreement from the person holding it",
            "Close a conversation with a decision, not an atmosphere",
        ],
        "modules": [
            ("The cost of the unspoken", [("Why delay compounds", "public")]),
            (
                "Saying it in the room",
                [("Opening without an accusation", "paid"), ("Holding the second minute", "paid")],
            ),
        ],
    },
    {
        "slug": "strategy-under-constraint",
        "title": "Strategy Under Constraint",
        "summary": (
            "Strategy when the budget, the headcount and the timeline are all fixed — "
            "choosing what not to do, and defending that choice."
        ),
        "topic": "Strategy",
        "level": "intermediate",
        "format": "blended",
        "workshop": True,
        "colour": "#4A3A52",
        "price": Decimal("2150.00"),
        "outcomes": [
            "State a strategy as a set of refusals, not a list of ambitions",
            "Defend a trade-off to a board without retreating into optionality",
            "Re-plan when a constraint moves without restarting from nothing",
        ],
        "modules": [
            ("Constraints as the input", [("What a constraint actually tells you", "public")]),
            (
                "Choosing what not to do",
                [("The refusal list", "paid"), ("Defending the trade-off", "paid")],
            ),
        ],
    },
    {
        "slug": "the-first-ninety-days-in-a-new-mandate",
        "title": "The First Ninety Days in a New Mandate",
        "summary": (
            "Arriving into a role with a mandate someone else wrote — and finding out what is "
            "actually true before committing to it."
        ),
        "topic": "Leadership",
        "level": "executive",
        "format": "self_paced",
        "workshop": False,
        "colour": "#2E4A5B",
        "price": Decimal("2100.00"),
        "outcomes": [
            "Test an inherited mandate against what the organisation actually does",
            "Choose the first visible decision deliberately",
            "Build the reporting line you need rather than the one you were handed",
        ],
        "modules": [
            ("Reading the room you inherited", [("What the mandate leaves out", "public")]),
            ("The first visible decision", [("Choosing it deliberately", "paid")]),
        ],
    },
    {
        "slug": "holding-a-team-through-change",
        "title": "Holding a Team Through Change",
        "summary": (
            "Restructures, mergers and mandate changes, from the point of view of the manager who "
            "has to keep the work going while it happens."
        ),
        "topic": "Team engagement",
        "level": "intermediate",
        "format": "live_cohort",
        "workshop": True,
        "colour": "#5B4A2E",
        "price": Decimal("1950.00"),
        "outcomes": [
            "Keep delivery going without pretending the change isn't happening",
            "Answer 'what does this mean for me' honestly when you don't fully know",
            "Spot the quiet disengagement that precedes a resignation",
        ],
        "modules": [
            ("What changes for the team", [("The questions nobody asks out loud", "public")]),
            ("Keeping the work going", [("Rhythm during a restructure", "paid")]),
        ],
    },
]

BODY = (
    "This lesson is part of the TTLI demo content set. It carries enough text for the "
    "reading-time estimate to be meaningful and for the completion rules to have something "
    "real to measure, without pretending to be the finished programme copy. "
) * 6


CERT_TITLE = "TTLI Executive Certificate"


async def _certificate_template(session: AsyncSession) -> uuid.UUID:
    """One shared template for the demo programmes — issuer, signatory and
    CPD points are what the certificate PDF and the course page's
    `.cert-preview` render."""
    template = (
        (
            await session.execute(
                select(CertificateTemplate).where(CertificateTemplate.title == CERT_TITLE)
            )
        )
        .scalars()
        .first()
    )
    if template is None:
        # CertificateTemplate is global, not tenant-scoped (models/credential.py).
        template = CertificateTemplate(
            id=uuid7(),
            title=CERT_TITLE,
            issuer_name="Themba Thandeka Leadership Institute",
            signatory_name="Dr N. Mokoena",
            signatory_title="Programme Director",
            cpd_points=4,
        )
        session.add(template)
        await session.flush()
    return template.id


async def _upsert_course(session: AsyncSession, spec: dict) -> Course:
    course = (
        await session.execute(select(Course).where(Course.slug == spec["slug"]))
    ).scalar_one_or_none()
    if course is None:
        course = Course(id=uuid7(), slug=spec["slug"], title=spec["title"])
        session.add(course)
        await session.flush()
    course.title = spec["title"]
    course.summary = spec["summary"]
    course.description = spec["summary"]
    course.topic = spec["topic"]
    course.level = spec["level"]
    course.format = spec["format"]
    course.includes_workshop = spec["workshop"]
    course.hero_colour = spec["colour"]
    course.outcomes = list(spec["outcomes"])
    course.completion_rules = {"minimum_time_seconds": 60}
    course.state = "published"
    await session.flush()

    existing_modules = (
        (await session.execute(select(Module).where(Module.course_id == course.id))).scalars().all()
    )
    by_title = {m.title: m for m in existing_modules}
    for m_index, (module_title, lessons) in enumerate(spec["modules"]):
        module = by_title.get(module_title)
        if module is None:
            module = Module(id=uuid7(), course_id=course.id, title=module_title, position=m_index)
            session.add(module)
            await session.flush()
        module.position = m_index
        existing_lessons = (
            (await session.execute(select(Lesson).where(Lesson.module_id == module.id)))
            .scalars()
            .all()
        )
        lessons_by_title = {x.title: x for x in existing_lessons}
        for l_index, (lesson_title, access) in enumerate(lessons):
            lesson = lessons_by_title.get(lesson_title)
            if lesson is None:
                lesson = Lesson(
                    id=uuid7(),
                    module_id=module.id,
                    title=lesson_title,
                    position=l_index,
                    activity_type="document",
                    access_level=access,
                    completion_rules={},
                )
                session.add(lesson)
            lesson.position = l_index
            lesson.access_level = access
            lesson.body = BODY
        await session.flush()
    return course


async def _assign_and_price(session: AsyncSession, course: Course, amount: Decimal) -> None:
    assignment = (
        await session.execute(
            select(CourseTenantAssignment).where(
                CourseTenantAssignment.course_id == course.id,
                CourseTenantAssignment.tenant_id == DEMO_TENANT,
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        session.add(
            CourseTenantAssignment(
                id=uuid7(), tenant_id=DEMO_TENANT, course_id=course.id, is_bespoke=False
            )
        )
        await session.flush()

    product = (
        await session.execute(
            select(Product).where(Product.course_id == course.id, Product.tenant_id == DEMO_TENANT)
        )
    ).scalar_one_or_none()
    if product is None:
        product = Product(
            id=uuid7(),
            tenant_id=DEMO_TENANT,
            slug=course.slug,
            name=course.title,
            description=course.summary,
            kind="course",
            course_id=course.id,
        )
        session.add(product)
        await session.flush()
    product.name = course.title
    product.description = course.summary
    product.is_active = True

    price = (
        (await session.execute(select(Price).where(Price.product_id == product.id)))
        .scalars()
        .first()
    )
    if price is None:
        price = Price(
            id=uuid7(),
            tenant_id=DEMO_TENANT,
            product_id=product.id,
            currency="ZAR",
            unit_amount=amount,
            tax_behaviour="inclusive",
        )
        session.add(price)
    else:
        price.unit_amount = amount
        price.tax_behaviour = "inclusive"
    await session.flush()


EPISODE_SLUG = "the-quiet-cost-of-unspoken-feedback"


async def _episode(session: AsyncSession, related_course_id: uuid.UUID | None) -> None:
    """One real episode, so the Resources page and the landing page's
    "Latest episode" card have honest content once the test episodes are
    unpublished (scripts/hide_test_courses.py). Authored, not curated:
    there is no audio file in the dev database, so it carries show notes,
    a transcript and a related programme rather than pretending to play."""
    episode = (
        await session.execute(
            select(PodcastEpisode).where(
                PodcastEpisode.tenant_id == DEMO_TENANT,
                PodcastEpisode.slug == EPISODE_SLUG,
            )
        )
    ).scalar_one_or_none()
    if episode is None:
        episode = PodcastEpisode(
            id=uuid7(), tenant_id=DEMO_TENANT, slug=EPISODE_SLUG, kind="authored", title=""
        )
        session.add(episode)
        await session.flush()
    episode.title = "The quiet cost of unspoken feedback"
    episode.description = (
        "Most executive teams do not have a feedback problem. They have a problem with the "
        "eleven days between noticing something and saying it."
    )
    episode.show_notes = (
        "02:10  Why delay compounds\n"
        "11:35  Seniority and silence\n"
        "18:40  The interval, not the script\n"
        "26:02  What to try on Monday"
    )
    episode.transcript = (
        "In this episode we look at what actually happens inside a leadership team when "
        "observations go unspoken — how the delay compounds, why seniority makes it worse "
        "rather than better, and what changes when a team agrees on a shorter interval "
        "rather than a better technique."
    )
    episode.related_course_id = related_course_id
    episode.duration_seconds = 1934
    episode.state = "published"
    episode.position = 0
    await session.flush()


ARTICLE_SLUG = "the-eleven-day-gap"
ARTICLE_BODY = (
    "## The gap that actually costs you\n\n"
    "Most executive teams do not have a feedback problem. They have a problem with the "
    "eleven days between noticing something and saying it.\n\n"
    "That number is not exact for any one team, but it is close for most of the ones we "
    "work with: the interval between a manager clocking a pattern and actually naming it "
    "out loud, in the room, to the person who could do something about it.\n\n"
    "### Why the delay compounds\n\n"
    "A observation that would have taken thirty seconds to raise in the moment turns into "
    "a prepared conversation by the time it is finally said — which means it arrives "
    "carrying more weight than the original moment ever had. The person on the receiving "
    "end reasonably asks why now, and why like this.\n\n"
    "### What to try instead\n\n"
    "Agree on a shorter interval as a team norm, not a better script for the eventual "
    "conversation. The technique matters less than the timing — this is the same idea "
    "*Leading Through Ambiguity* spends its second module on.\n"
)


async def _article(session: AsyncSession, related_course_id: uuid.UUID | None) -> None:
    """One real article, so the Resources hub's "Writing" section has
    honest content once the test articles pytest leaves behind are
    unpublished (scripts/hide_test_courses.py) — the same "one real row
    over 1,300 test rows" convention `_episode` already established."""
    article = (
        await session.execute(
            select(Article).where(Article.tenant_id == DEMO_TENANT, Article.slug == ARTICLE_SLUG)
        )
    ).scalar_one_or_none()
    if article is None:
        article = Article(
            id=uuid7(), tenant_id=DEMO_TENANT, slug=ARTICLE_SLUG, title="", body=""
        )
        session.add(article)
        await session.flush()
    article.title = "The eleven-day gap"
    article.dek = "Most executive teams do not have a feedback problem. They have a timing problem."
    article.body = ARTICLE_BODY
    article.author_name = "Dr N. Mokoena"
    article.related_course_id = related_course_id
    article.state = "published"
    article.published_at = article.published_at or datetime.now(UTC)
    article.reading_minutes = max(1, round(len(ARTICLE_BODY.split()) / 200))
    article.position = 0
    await session.flush()


DEMO_TENANT: uuid.UUID  # set in main() from the database


async def _demo_tenant(session: AsyncSession) -> uuid.UUID:
    """Resolved by slug, never hardcoded: the demo tenant's id is
    generated by migration 0002, so it differs between databases and
    changes whenever the volume is recreated."""
    tenant_id = (
        await session.execute(text("SELECT id FROM tenants WHERE slug = 'demo'"))
    ).scalar_one_or_none()
    if tenant_id is None:
        raise SystemExit("no 'demo' tenant — run alembic upgrade head first")
    return uuid.UUID(str(tenant_id))


async def main() -> None:
    settings = get_settings()
    if settings.environment not in ("local", "development", "dev"):
        raise SystemExit(f"refusing to seed demo content in ENVIRONMENT={settings.environment!r}")
    init_engine(settings)
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        # Resolve before set_tenant: the RLS GUC needs the real id.
        global DEMO_TENANT
        DEMO_TENANT = await _demo_tenant(session)
        demo_tenant = DEMO_TENANT
        await set_tenant(session, demo_tenant)
        template_id = await _certificate_template(session)
        first_course_id: uuid.UUID | None = None
        for spec in PROGRAMMES:
            course = await _upsert_course(session, spec)
            course.certificate_template_id = template_id
            await _assign_and_price(session, course, spec["price"])
            first_course_id = first_course_id or course.id
            print(f"seeded {course.slug}")
        await _episode(session, first_course_id)
        print(f"seeded episode {EPISODE_SLUG}")
        await _article(session, first_course_id)
        print(f"seeded article {ARTICLE_SLUG}")
    print(
        f"done — {len(PROGRAMMES)} programmes published, assigned and priced, "
        "1 episode, 1 article"
    )


asyncio.run(main())

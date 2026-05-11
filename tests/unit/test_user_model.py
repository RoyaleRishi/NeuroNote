"""Unit tests for the User model (public.users table)."""
from __future__ import annotations

from sqlalchemy import inspect

from app.db.engine import get_engine, get_session_factory
from app.db.models.user import User


def test_users_table_exists(configured_db: None) -> None:
    inspector = inspect(get_engine())
    assert "users" in inspector.get_table_names()


def test_users_table_columns(configured_db: None) -> None:
    inspector = inspect(get_engine())
    columns = {col["name"] for col in inspector.get_columns("users")}
    expected = {
        "id",
        "email",
        "display_name",
        "avatar_url",
        "oauth_provider",
        "oauth_provider_id",
        "schema_name",
        "created_at",
        "last_login_at",
    }
    assert expected.issubset(columns)


def test_users_unique_constraints(configured_db: None) -> None:
    inspector = inspect(get_engine())
    uniques = inspector.get_unique_constraints("users")
    unique_column_sets = [
        sorted(uc.get("column_names", [])) for uc in uniques
    ]
    # email unique
    assert ["email"] in unique_column_sets
    # schema_name unique
    assert ["schema_name"] in unique_column_sets
    # (oauth_provider, oauth_provider_id) unique
    assert ["oauth_provider", "oauth_provider_id"] in unique_column_sets


def test_user_insert_and_read(configured_db: None) -> None:
    factory = get_session_factory()
    with factory() as session:
        user = User(
            email="test@example.com",
            display_name="Test User",
            avatar_url="https://example.com/avatar.png",
            oauth_provider="google",
            oauth_provider_id="google-123",
            schema_name="user_abc123",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        assert user.id is not None
        assert user.email == "test@example.com"
        assert user.display_name == "Test User"
        assert user.oauth_provider == "google"
        assert user.oauth_provider_id == "google-123"
        assert user.schema_name == "user_abc123"
        assert user.created_at is not None
        assert user.last_login_at is None


def test_user_email_uniqueness(configured_db: None) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    factory = get_session_factory()
    with factory() as session:
        user1 = User(
            email="dupe@example.com",
            oauth_provider="google",
            oauth_provider_id="g-1",
            schema_name="user_001",
        )
        session.add(user1)
        session.commit()

    with factory() as session:
        user2 = User(
            email="dupe@example.com",
            oauth_provider="github",
            oauth_provider_id="gh-1",
            schema_name="user_002",
        )
        session.add(user2)
        with pytest.raises(IntegrityError):
            session.commit()


def test_user_schema_name_uniqueness(configured_db: None) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    factory = get_session_factory()
    with factory() as session:
        user1 = User(
            email="a@example.com",
            oauth_provider="google",
            oauth_provider_id="g-a",
            schema_name="user_same",
        )
        session.add(user1)
        session.commit()

    with factory() as session:
        user2 = User(
            email="b@example.com",
            oauth_provider="github",
            oauth_provider_id="gh-b",
            schema_name="user_same",
        )
        session.add(user2)
        with pytest.raises(IntegrityError):
            session.commit()


def test_user_oauth_provider_uniqueness(configured_db: None) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    factory = get_session_factory()
    with factory() as session:
        user1 = User(
            email="c@example.com",
            oauth_provider="google",
            oauth_provider_id="same-id",
            schema_name="user_c1",
        )
        session.add(user1)
        session.commit()

    with factory() as session:
        user2 = User(
            email="d@example.com",
            oauth_provider="google",
            oauth_provider_id="same-id",
            schema_name="user_c2",
        )
        session.add(user2)
        with pytest.raises(IntegrityError):
            session.commit()

"""Tests for podcast.models."""

from datetime import datetime, timezone

from podcast.models import Base, Episode, Job, LogEntry, PodcastSettings, User, utcnow


class TestUtcnow:
    def test_returns_utc_datetime(self):
        result = utcnow()
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    def test_is_recent(self):
        before = datetime.now(timezone.utc)
        result = utcnow()
        after = datetime.now(timezone.utc)
        assert before <= result <= after


class TestEpisodeModel:
    def test_tablename(self):
        assert Episode.__tablename__ == "episodes"

    def test_has_expected_columns(self):
        col_names = {c.name for c in Episode.__table__.columns}
        expected = {
            "id", "user_id", "title", "description", "topic", "status",
            "error_message", "failed_step", "research_notes", "transcript",
            "audio_filename", "audio_duration_seconds", "audio_size_bytes",
            "episode_number", "published_at", "created_at", "updated_at",
        }
        assert expected.issubset(col_names)

    def test_status_default(self):
        col = Episode.__table__.columns["status"]
        assert col.default.arg == "pending"

    def test_has_jobs_relationship(self):
        assert "jobs" in Episode.__mapper__.relationships

    def test_jobs_cascade_delete_orphan(self):
        rel = Episode.__mapper__.relationships["jobs"]
        assert "delete-orphan" in rel.cascade


class TestJobModel:
    def test_tablename(self):
        assert Job.__tablename__ == "jobs"

    def test_has_expected_columns(self):
        col_names = {c.name for c in Job.__table__.columns}
        expected = {
            "id", "episode_id", "step", "status", "error_message",
            "attempts", "max_attempts", "created_at", "started_at",
            "completed_at", "metrics_json",
        }
        assert expected.issubset(col_names)

    def test_episode_foreign_key(self):
        col = Job.__table__.columns["episode_id"]
        fk = list(col.foreign_keys)[0]
        assert fk.target_fullname == "episodes.id"

    def test_cascade_delete_on_fk(self):
        col = Job.__table__.columns["episode_id"]
        fk = list(col.foreign_keys)[0]
        assert fk.ondelete == "CASCADE"

    def test_default_attempts(self):
        col = Job.__table__.columns["attempts"]
        assert col.default.arg == 0

    def test_default_max_attempts(self):
        col = Job.__table__.columns["max_attempts"]
        assert col.default.arg == 3


class TestPodcastSettingsModel:
    def test_tablename(self):
        assert PodcastSettings.__tablename__ == "podcast_settings"

    def test_default_title(self):
        col = PodcastSettings.__table__.columns["title"]
        assert col.default.arg == "My Private Podcast"

    def test_default_host_names(self):
        col_a = PodcastSettings.__table__.columns["host_a_name"]
        col_b = PodcastSettings.__table__.columns["host_b_name"]
        assert col_a.default.arg == "Alex"
        assert col_b.default.arg == "Sam"

    def test_user_id_foreign_key(self):
        col = PodcastSettings.__table__.columns["user_id"]
        fk = list(col.foreign_keys)[0]
        assert fk.target_fullname == "users.id"

    def test_user_id_is_unique(self):
        col = PodcastSettings.__table__.columns["user_id"]
        assert col.unique is True


class TestUserModel:
    def test_tablename(self):
        assert User.__tablename__ == "users"

    def test_has_expected_columns(self):
        col_names = {c.name for c in User.__table__.columns}
        expected = {"id", "shoo_sub", "enabled", "is_admin", "feed_token", "created_at"}
        assert expected.issubset(col_names)

    def test_shoo_sub_is_unique(self):
        col = User.__table__.columns["shoo_sub"]
        assert col.unique is True

    def test_feed_token_is_unique(self):
        col = User.__table__.columns["feed_token"]
        assert col.unique is True

    def test_enabled_default(self):
        col = User.__table__.columns["enabled"]
        assert col.default.arg is True

    def test_is_admin_default(self):
        col = User.__table__.columns["is_admin"]
        assert col.default.arg is False


class TestLogEntryModel:
    def test_tablename(self):
        assert LogEntry.__tablename__ == "log_entries"

    def test_has_expected_columns(self):
        col_names = {c.name for c in LogEntry.__table__.columns}
        expected = {"id", "timestamp", "level", "logger_name", "message", "source"}
        assert expected.issubset(col_names)

    def test_id_is_autoincrement(self):
        col = LogEntry.__table__.columns["id"]
        assert col.autoincrement is not False  # True or "auto"


class TestBase:
    def test_is_declarative_base(self):
        assert hasattr(Base, "metadata")
        assert hasattr(Base, "registry")

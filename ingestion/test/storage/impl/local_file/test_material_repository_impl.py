"""验证本地资料索引、幂等更新与两个字幕文件的一致性。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ingestion.entity import Platform, SubtitleMaterialEntity, SubtitleSegment
from ingestion.storage.error import RepositoryConflictError
from ingestion.storage.impl.local_file import material_repository_impl
from ingestion.storage.impl.local_file.avatar_repository_impl import AvatarRepositoryImpl
from ingestion.storage.impl.local_file.material_repository_impl import MaterialRepositoryImpl


class MaterialRepositoryTest(TestCase):
    """通过真实临时目录测试完整资料的保存和恢复。"""

    def setUp(self) -> None:
        """登记测试作者并建立独立的仓储实例。"""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.avatars = AvatarRepositoryImpl(self.root)
        self.materials = MaterialRepositoryImpl(self.root)
        avatar = self.avatars.create("作者", ["https://space.bilibili.com/42"])
        now = datetime.now(UTC)
        self.raw = SubtitleMaterialEntity(
            id=self.materials.reserve_id(), created_at=now, updated_at=now, author_id=avatar.id,
            platform=Platform.BILIBILI, source_key="BV1xx411c7mD",
            raw_segments=[SubtitleSegment(0.124, 2, "第一行\n第二行")],
            optimized_segments=[SubtitleSegment(0.124, 2, "优化稿", "小节", ("标签",))],
            global_keywords=("全文",),
        )

    def test_restart_and_conditional_update(self) -> None:
        """重启可读回两稿，过时写入被拒绝，删除加工稿保留原稿。"""
        self.materials.save(self.raw)
        reopened = MaterialRepositoryImpl(self.root)
        stored = reopened.get_by_id(self.raw.id)
        self.assertEqual(stored.raw_segments, self.raw.raw_segments)
        self.assertEqual(stored.optimized_segments, self.raw.optimized_segments)
        self.assertEqual(stored.global_keywords, ("全文",))
        self.assertEqual(reopened.get(stored.author_id, stored.platform, stored.source_key), stored)
        self.assertGreater(reopened.reserve_id(), stored.id)
        with self.assertRaises(RepositoryConflictError):
            self.avatars.delete(stored.author_id)

        reopened.save(replace(stored, optimized_segments=[], global_keywords=()), expected_updated_at=stored.updated_at)
        fresh = self.materials.get_by_id(stored.id)
        self.assertEqual(fresh.raw_segments, stored.raw_segments)
        self.assertEqual(fresh.created_at, stored.created_at)
        self.assertGreater(fresh.updated_at, stored.updated_at)
        self.assertEqual(fresh.optimized_segments, [])
        self.assertEqual(list(self.root.rglob("processed/*.json")), [])
        with self.assertRaises(RepositoryConflictError):
            self.materials.save(stored, expected_updated_at=stored.updated_at)

        reopened.delete(stored.id)
        self.assertIsNone(self.materials.get_by_id(stored.id))
        self.avatars.delete(stored.author_id)
        self.assertIsNone(self.avatars.get(stored.author_id))

    def test_failed_index_commit_keeps_both_old_files(self) -> None:
        """写入新版稿件后若索引提交失败，重开仍只读到原来的两稿。"""
        self.materials.save(self.raw)
        before = self.materials.get_by_id(self.raw.id)
        files_before = sorted(self.root.rglob("*.*"))

        def fail_index(path: Path, value: object) -> None:
            """在索引最终替换时注入写入错误。

            :param path: 待写入文件。
            :param value: 待序列化内容。
            :raises OSError: 当前目标是最终索引。
            """
            if path.name == "materials.json":
                raise OSError("模拟索引提交失败")
            write_json(path, value)

        write_json = material_repository_impl.write_json
        with patch.object(material_repository_impl, "write_json", side_effect=fail_index):
            with self.assertRaises(OSError):
                self.materials.save(
                    replace(before, raw_segments=[SubtitleSegment(0, 2, "新原稿")]),
                    expected_updated_at=before.updated_at,
                )
        self.assertEqual(MaterialRepositoryImpl(self.root).get_by_id(before.id), before)
        self.assertEqual(sorted(self.root.rglob("*.*")), files_before)

    def test_concurrent_id_reservation(self) -> None:
        """验证多个仓储实例并发预留资料 ID 时不会重复分配。"""
        with ThreadPoolExecutor(max_workers=6) as pool:
            reservations = [pool.submit(MaterialRepositoryImpl(self.root).reserve_id) for _ in range(12)]
            ids = sorted(task.result() for task in reservations)
        self.assertEqual(ids, list(range(self.raw.id + 1, self.raw.id + 13)))

"""将采集服务的返回信息渲染为命令行文本。"""

import sys
from collections.abc import Sequence
from datetime import datetime

from ...service import (
    AvatarInfo,
    CollectAndProcessResult,
    CollectionResult,
    MaterialDetail,
    MaterialPage,
    ProcessingResult,
    ResultStatus,
    SubtitleMaterialDetail,
    SubtitleSegmentInfo,
)


_STATUS_LABELS = {
    ResultStatus.SUCCESS: "成功",
    ResultStatus.SKIPPED: "已跳过",
    ResultStatus.NOT_REQUIRED: "无需加工",
    ResultStatus.FAILED: "失败",
}


def _format_date(value: datetime | None) -> str:
    """将服务返回的时间格式化为可读文本。

    :param value: 带时区的时间。为 None 时表示未知。
    :returns: 保留时区的日期时间文本，未知时为短横线。
    """
    return value.isoformat(sep=" ", timespec="seconds") if value is not None else "-"


def show_avatars(avatars: Sequence[AvatarInfo]) -> None:
    """显示可供后续采集命令选择的本地博主。

    :param avatars: 已登记博主的列表。空列表时显示提示。
    """
    if not avatars:
        print("暂无已登记的博主。")
        return
    print("博主 ID\t名称\t平台")
    for avatar in avatars:
        platforms = "、".join(account.platform.value for account in avatar.platforms) or "-"
        print(f"{avatar.id}\t{avatar.name}\t{platforms}")


def show_remote_materials(page: MaterialPage) -> None:
    """显示远端资料和继续分页所需的页码。

    :param page: 服务返回的一页资料和下一页信息。
    """
    if page.items:
        print("来源标识\t标题\t发布时间")
        for item in page.items:
            print(f"{item.source_key}\t{item.title or '-'}\t{_format_date(item.published_at)}")
    else:
        print("本页暂无远端资料。")
    if page.next_page is None:
        print("没有下一页。")
    else:
        print(f"下一页：{page.next_page}")


def show_local_materials(materials: Sequence[MaterialDetail]) -> None:
    """显示本地资料及可用于查询和加工的资料 ID。

    :param materials: 服务返回的本地资料列表。空列表时显示提示。
    """
    if not materials:
        print("暂无本地资料。")
        return
    print("资料 ID\t平台\t标题\t发布时间")
    for material in materials:
        print(
            f"{material.id}\t{material.platform.value}\t"
            f"{material.title or '-'}\t{_format_date(material.published_at)}"
        )


def _show_segments(
    heading: str,
    segments: Sequence[SubtitleSegmentInfo],
    empty_message: str,
) -> None:
    """显示一份字幕的带时间片段。

    :param heading: 用于区分原始字幕与加工稿的标题。
    :param segments: 按字幕顺序排列的片段，时间单位为秒。
    :param empty_message: 没有片段时显示的提示。
    """
    print(heading)
    if not segments:
        print(empty_message)
        return
    for segment in segments:
        print(f"[{segment.start_seconds:.3f}s - {segment.end_seconds:.3f}s] {segment.text}")


def show_material(material: MaterialDetail) -> None:
    """显示资料来源和字幕详情。

    :param material: 服务返回的本地资料详情。
    """
    print(f"资料 ID：{material.id}")
    print(f"标题：{material.title or '-'}")
    print(f"平台：{material.platform.value}")
    print(f"来源标识：{material.source_key}")
    print(f"来源链接：{material.source_url or '-'}")
    print(f"发布时间：{_format_date(material.published_at)}")
    if isinstance(material, SubtitleMaterialDetail):
        _show_segments("原始字幕", material.raw_segments, "暂无原始字幕。")
        _show_segments("加工稿", material.optimized_segments, "暂无加工稿。")


def show_results(results: Sequence[CollectionResult | ProcessingResult]) -> int:
    """按服务给出的顺序显示采集或加工结果。

    :param results: 单条或批量操作的结果。失败项包含可供展示的原因。
    :returns: 有失败项时返回 1，否则返回 0。
    """
    failed = False
    for result in results:
        if isinstance(result, CollectionResult):
            target = f"来源标识 {result.source_key}"
            if result.material is not None:
                target += f"（资料 ID {result.material.id}）"
        else:
            target = f"资料 ID {result.material_id}"
        line = f"{target}：{_STATUS_LABELS[result.status]}"
        # 逐项刷新两个输出流，便于将标准输出和标准错误合并时保留结果顺序。
        if result.status == ResultStatus.FAILED:
            print(f"{line}。{result.error or '服务未提供失败原因。'}", file=sys.stderr, flush=True)
            failed = True
        else:
            print(line, flush=True)
    return int(failed)


def show_collect_and_process_result(result: CollectAndProcessResult) -> int:
    """分别展示同一份资料的采集与加工结果。

    :param result: 全链路服务返回的分阶段结果。
    :returns: 有阶段失败时返回 1，否则返回 0。
    """
    print("采集")
    collected = show_results([result.collection])
    if result.processing is None:
        return collected
    print("加工")
    return max(collected, show_results([result.processing]))

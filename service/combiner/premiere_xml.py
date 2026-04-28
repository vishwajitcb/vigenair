"""Generates Adobe Premiere Pro / FCP7 XML (xmeml v5) for variant timelines.

The output references **per-segment** clip files arranged in a bundle:

    timeline.xml
    media/clip_001.mp4   (video + audio, H.264)
    media/clip_002.mp4
    ...
    music/clip_001.wav   (audio-only, PCM)
    music/clip_002.wav
    ...

The XML's video track points at `media/clip_NNN.mp4` and the audio track
points at `music/clip_NNN.wav` for each segment, linked together so they
move as one in Premiere. Each clipitem starts at the file's frame 0 (in=0,
out=<clip duration>) — no relinking dance needed for the editor.
"""

from xml.etree import ElementTree as ET
from xml.dom import minidom


_NTSC_RATES = {
    23.976: 24,
    23.98: 24,
    29.97: 30,
    47.952: 48,
    47.95: 48,
    59.94: 60,
}


def _rate_attrs(fps: float) -> tuple[int, str]:
    for ntsc_rate, timebase in _NTSC_RATES.items():
        if abs(fps - ntsc_rate) < 0.01:
            return timebase, "TRUE"
    return int(round(fps)) if fps > 0 else 30, "FALSE"


def _seconds_to_frames(seconds: float, fps: float) -> int:
    return int(round(seconds * fps))


def _add_rate(parent: ET.Element, timebase: int, ntsc: str) -> None:
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = ntsc


def _build_video_file(
    file_id: str,
    rel_path: str,
    duration_frames: int,
    timebase: int,
    ntsc: str,
    width: int,
    height: int,
) -> ET.Element:
    file_el = ET.Element("file", id=file_id)
    name = rel_path.rsplit("/", 1)[-1]
    ET.SubElement(file_el, "name").text = name
    ET.SubElement(file_el, "pathurl").text = f"file://localhost/{rel_path}"
    _add_rate(file_el, timebase, ntsc)
    ET.SubElement(file_el, "duration").text = str(duration_frames)
    media = ET.SubElement(file_el, "media")
    video = ET.SubElement(media, "video")
    video_sc = ET.SubElement(video, "samplecharacteristics")
    ET.SubElement(video_sc, "width").text = str(width)
    ET.SubElement(video_sc, "height").text = str(height)
    audio = ET.SubElement(media, "audio")
    ET.SubElement(audio, "channelcount").text = "2"
    return file_el


def _build_audio_file(
    file_id: str,
    rel_path: str,
    duration_frames: int,
    timebase: int,
    ntsc: str,
    samplerate: int = 48000,
) -> ET.Element:
    file_el = ET.Element("file", id=file_id)
    name = rel_path.rsplit("/", 1)[-1]
    ET.SubElement(file_el, "name").text = name
    ET.SubElement(file_el, "pathurl").text = f"file://localhost/{rel_path}"
    _add_rate(file_el, timebase, ntsc)
    ET.SubElement(file_el, "duration").text = str(duration_frames)
    media = ET.SubElement(file_el, "media")
    audio = ET.SubElement(media, "audio")
    audio_sc = ET.SubElement(audio, "samplecharacteristics")
    ET.SubElement(audio_sc, "depth").text = "16"
    ET.SubElement(audio_sc, "samplerate").text = str(samplerate)
    ET.SubElement(audio, "channelcount").text = "2"
    return file_el


def _video_clipitem(
    clip_id: str,
    name: str,
    timeline_start: int,
    timeline_end: int,
    clip_frames: int,
    timebase: int,
    ntsc: str,
    file_element: ET.Element,
    linked_audio_id: str,
) -> ET.Element:
    ci = ET.Element("clipitem", id=clip_id)
    ET.SubElement(ci, "name").text = name
    ET.SubElement(ci, "enabled").text = "TRUE"
    ET.SubElement(ci, "duration").text = str(clip_frames)
    _add_rate(ci, timebase, ntsc)
    ET.SubElement(ci, "start").text = str(timeline_start)
    ET.SubElement(ci, "end").text = str(timeline_end)
    ET.SubElement(ci, "in").text = "0"
    ET.SubElement(ci, "out").text = str(clip_frames)
    ci.append(file_element)
    link = ET.SubElement(ci, "link")
    ET.SubElement(link, "linkclipref").text = linked_audio_id
    ET.SubElement(link, "mediatype").text = "audio"
    return ci


def _audio_clipitem(
    clip_id: str,
    name: str,
    timeline_start: int,
    timeline_end: int,
    clip_frames: int,
    timebase: int,
    ntsc: str,
    file_element: ET.Element,
    linked_video_id: str,
) -> ET.Element:
    ci = ET.Element("clipitem", id=clip_id)
    ET.SubElement(ci, "name").text = name
    ET.SubElement(ci, "enabled").text = "TRUE"
    ET.SubElement(ci, "duration").text = str(clip_frames)
    _add_rate(ci, timebase, ntsc)
    ET.SubElement(ci, "start").text = str(timeline_start)
    ET.SubElement(ci, "end").text = str(timeline_end)
    ET.SubElement(ci, "in").text = "0"
    ET.SubElement(ci, "out").text = str(clip_frames)
    ci.append(file_element)
    st = ET.SubElement(ci, "sourcetrack")
    ET.SubElement(st, "mediatype").text = "audio"
    ET.SubElement(st, "trackindex").text = "1"
    link = ET.SubElement(ci, "link")
    ET.SubElement(link, "linkclipref").text = linked_video_id
    ET.SubElement(link, "mediatype").text = "video"
    return ci


def generate_premiere_xml(
    variant_id,
    title: str,
    clips: list,
    width: int,
    height: int,
    fps: float,
) -> str:
    """Build a Premiere FCP7 XML referencing per-segment clip files.

    Args:
        variant_id: id used to derive sequence/clip ids.
        title: sequence name.
        clips: ordered list of dicts, each:
            {
                "video_rel_path": "media/clip_001.mp4",
                "audio_rel_path": "music/clip_001.wav",
                "duration_s": 2.5,
                "name": "Segment 4",   # display name in Premiere
            }
        width, height: shared sample characteristics for the sequence.
        fps: source frame rate.
    """
    if not clips:
        raise ValueError("clips must not be empty")

    timebase, ntsc = _rate_attrs(fps)

    xmeml = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(xmeml, "sequence", id=f"sequence-{variant_id}")
    ET.SubElement(sequence, "name").text = title or f"Variant {variant_id}"
    _add_rate(sequence, timebase, ntsc)

    media = ET.SubElement(sequence, "media")
    video_root = ET.SubElement(media, "video")
    video_format = ET.SubElement(video_root, "format")
    video_sc = ET.SubElement(video_format, "samplecharacteristics")
    _add_rate(video_sc, timebase, ntsc)
    ET.SubElement(video_sc, "width").text = str(width)
    ET.SubElement(video_sc, "height").text = str(height)
    video_track = ET.SubElement(video_root, "track")

    audio_root = ET.SubElement(media, "audio")
    audio_track = ET.SubElement(audio_root, "track")

    timeline_cursor = 0
    sequence_total_frames = 0

    for idx, clip in enumerate(clips):
        clip_frames = _seconds_to_frames(float(clip["duration_s"]), fps)
        if clip_frames <= 0:
            continue
        timeline_start = timeline_cursor
        timeline_end = timeline_cursor + clip_frames

        video_clip_id = f"clip-v-{variant_id}-{idx}"
        audio_clip_id = f"clip-a-{variant_id}-{idx}"
        video_file_id = f"file-v-{variant_id}-{idx}"
        audio_file_id = f"file-a-{variant_id}-{idx}"

        video_file = _build_video_file(
            video_file_id,
            clip["video_rel_path"],
            clip_frames,
            timebase,
            ntsc,
            width,
            height,
        )
        audio_file = _build_audio_file(
            audio_file_id,
            clip["audio_rel_path"],
            clip_frames,
            timebase,
            ntsc,
        )

        clip_name = clip.get("name") or f"Clip {idx + 1}"

        video_track.append(
            _video_clipitem(
                video_clip_id,
                clip_name,
                timeline_start,
                timeline_end,
                clip_frames,
                timebase,
                ntsc,
                video_file,
                audio_clip_id,
            )
        )
        audio_track.append(
            _audio_clipitem(
                audio_clip_id,
                clip_name,
                timeline_start,
                timeline_end,
                clip_frames,
                timebase,
                ntsc,
                audio_file,
                video_clip_id,
            )
        )

        timeline_cursor = timeline_end
        sequence_total_frames = timeline_end

    ET.SubElement(sequence, "duration").text = str(sequence_total_frames)

    rough = ET.tostring(xmeml, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    body = pretty.split("\n", 1)[1] if pretty.startswith("<?xml") else pretty
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE xmeml>\n'
        + body
    )

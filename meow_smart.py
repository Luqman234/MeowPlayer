from dataclasses import dataclass


@dataclass(frozen=True)
class SmartPlaylist:
    key: str
    label: str
    description: str
    indices: tuple


def _stats_for(metadata, stats_by_path, index):
    path = str(metadata[index].path.resolve())
    return stats_by_path.get(
        path,
        {
            "favorite": False,
            "play_count": 0,
            "last_played_ns": None,
            "added_at_ns": 0,
        },
    )


def build_smart_playlists(metadata, stats_by_path):
    indices = list(range(len(metadata)))

    pawmarked = [
        index
        for index in indices
        if _stats_for(metadata, stats_by_path, index)["favorite"]
    ]

    recent = sorted(
        (
            index
            for index in indices
            if _stats_for(metadata, stats_by_path, index)["last_played_ns"]
            is not None
        ),
        key=lambda index: (
            -int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["last_played_ns"]
                or 0
            ),
            metadata[index].title.casefold(),
        ),
    )

    most_played = sorted(
        (
            index
            for index in indices
            if int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["play_count"]
            )
            > 0
        ),
        key=lambda index: (
            -int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["play_count"]
            ),
            -int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["last_played_ns"]
                or 0
            ),
            metadata[index].title.casefold(),
        ),
    )

    fresh = sorted(
        indices,
        key=lambda index: (
            -int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["added_at_ns"]
                or 0
            ),
            metadata[index].title.casefold(),
        ),
    )[:100]

    unplayed = sorted(
        (
            index
            for index in indices
            if int(
                _stats_for(
                    metadata,
                    stats_by_path,
                    index,
                )["play_count"]
            )
            == 0
        ),
        key=lambda index: (
            metadata[index].artist.casefold(),
            metadata[index].album.casefold(),
            metadata[index].track_number or 999999,
            metadata[index].title.casefold(),
        ),
    )

    playlists = [
        SmartPlaylist(
            "pawmarked",
            "Pawmarked Mix",
            "Every track carrying your Pawmark.",
            tuple(pawmarked),
        ),
        SmartPlaylist(
            "recent",
            "Recently Purrred",
            "Tracks ordered by the last time you played them.",
            tuple(recent),
        ),
        SmartPlaylist(
            "most-played",
            "Most Purrred",
            "Your most frequently played tracks.",
            tuple(most_played),
        ),
        SmartPlaylist(
            "fresh",
            "Fresh Finds",
            "The newest tracks known to the Cat Catalog.",
            tuple(fresh),
        ),
        SmartPlaylist(
            "unplayed",
            "Never Purrred",
            "Tracks with a play count of zero.",
            tuple(unplayed),
        ),
    ]

    genres = {}
    for index, meta in enumerate(metadata):
        genre = (meta.genre or "").strip()
        if not genre:
            continue
        genres.setdefault(genre, []).append(index)

    for genre in sorted(genres, key=str.casefold):
        genre_indices = sorted(
            genres[genre],
            key=lambda index: (
                metadata[index].artist.casefold(),
                metadata[index].album.casefold(),
                metadata[index].track_number or 999999,
                metadata[index].title.casefold(),
            ),
        )
        playlists.append(
            SmartPlaylist(
                f"genre:{genre}",
                f"Genre Mix · {genre}",
                f"Every track tagged as {genre}.",
                tuple(genre_indices),
            )
        )

    return playlists

from dataclasses import dataclass


@dataclass
class RunCommands:
    """Sub-commands for running each pipeline layer."""

    def bronze(self):
        """Replicate all Bronze tables from Postgres → Delta Lake."""
        import accrue.datajobs.bronze  # noqa: F401  (runs on import)

    def silver(self):
        """Apply Silver cleaning transforms on Bronze Delta tables."""
        import accrue.datajobs.silver  # noqa: F401  (runs on import)

    def gold(self):
        """Build Gold reporting tables from Silver Delta tables."""
        import accrue.datajobs.gold  # noqa: F401  (runs on import)


@dataclass
class CLI:

    def version(self):
        from accrue import version
        return version

    @property
    def run(self) -> RunCommands:
        """Run a pipeline layer: bronze | silver | gold."""
        return RunCommands()


def main():
    import fire

    fire.Fire(CLI())


if __name__ == "__main__":
    main()

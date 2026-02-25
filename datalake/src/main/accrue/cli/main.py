from dataclasses import dataclass


@dataclass
class CLI:

    def version(self):
        from accrue import version
        return version


def main():
    import fire
    
    fire.Fire(CLI())


if __name__ == "__main__":
    main()

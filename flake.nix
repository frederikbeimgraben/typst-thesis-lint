{
  description = "typst-thesis-lint - linter for papers and theses written in Typst";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      pkgsFor = system: nixpkgs.legacyPackages.${system};

      # Tools that the linter needs at run time. uv installs the Python packages.
      toolsFor = pkgs: [ pkgs.python314 pkgs.uv pkgs.typst pkgs.gcc pkgs.git ];

      envFor = pkgs: {
        UV_PYTHON = "${pkgs.python314}/bin/python3.14";
        UV_PYTHON_DOWNLOADS = "never";
      };
    in
    {
      devShells = forAllSystems (system:
        let pkgs = pkgsFor system; in
        {
          default = pkgs.mkShell ({
            # ruff and basedpyright from nixpkgs, because the PyPI wheels do not run on NixOS.
            packages = toolsFor pkgs ++ [ pkgs.rustup pkgs.ruff pkgs.basedpyright ];
          } // envFor pkgs);
        });

      apps = forAllSystems (system:
        let
          pkgs = pkgsFor system;
          env = envFor pkgs;
          # Run the CLI from a checkout of this repository. The first argument
          # of the wrapper is not needed: uv finds the project from the script path.
          lint = pkgs.writeShellApplication {
            name = "thesis-lint";
            runtimeInputs = toolsFor pkgs;
            text = ''
              export UV_PYTHON="${env.UV_PYTHON}"
              export UV_PYTHON_DOWNLOADS=never
              project="''${THESIS_LINT_PROJECT:-${self}}"
              exec uv run --quiet --frozen --project "$project" thesis-lint "$@"
            '';
          };
        in
        {
          default = { type = "app"; program = "${lint}/bin/thesis-lint"; };
        });
    };
}

//! Zed extension that starts the typst-thesis-lint language server.
//!
//! The extension looks for the server command in this order:
//! 1. The setting `lsp.thesis-lint.binary.path` with optional `arguments` and `env`.
//!    A relative path is relative to the root of the worktree.
//! 2. An executable `thesis-lint` on the PATH of the worktree, with the argument `lsp`.

use zed_extension_api::{self as zed, settings::LspSettings, LanguageServerId, Result};

const SERVER_NAME: &str = "thesis-lint";

struct ThesisLintExtension;

impl zed::Extension for ThesisLintExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        _language_server_id: &LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<zed::Command> {
        let binary = LspSettings::for_worktree(SERVER_NAME, worktree)
            .ok()
            .and_then(|settings| settings.binary);
        let configured = binary.as_ref().and_then(|b| b.path.clone());
        let env = binary
            .as_ref()
            .and_then(|b| b.env.clone())
            .map(|env| env.into_iter().collect())
            .unwrap_or_else(|| worktree.shell_env());
        if let Some(path) = configured {
            let command = if path.starts_with('/') {
                path
            } else {
                format!("{}/{}", worktree.root_path(), path)
            };
            let args = binary
                .and_then(|b| b.arguments)
                .unwrap_or_else(|| vec!["lsp".to_string()]);
            return Ok(zed::Command { command, args, env });
        }
        let command = worktree.which(SERVER_NAME).ok_or_else(|| {
            "thesis-lint is not on PATH. Set lsp.thesis-lint.binary.path in the settings."
                .to_string()
        })?;
        Ok(zed::Command {
            command,
            args: vec!["lsp".to_string()],
            env,
        })
    }
}

zed::register_extension!(ThesisLintExtension);

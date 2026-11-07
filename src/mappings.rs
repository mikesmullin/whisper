//! Spoken-phrase mappings: words to text or key combos, phrases to shell
//! commands, and the always-on activation keywords.
//!
//! Matching semantics are carried over from the Python build, because muscle
//! memory depends on them:
//!
//! - word mappings match on word boundaries, longest trigger first, and
//!   swallow trailing punctuation and whitespace
//! - a replacement containing `+` and shorter than 20 characters is a key
//!   combo, not literal text (checked *before* `{{clipboard}}` is resolved, so
//!   pasted content cannot accidentally look like one)
//! - command and activation phrases match the whole buffered utterance, with
//!   non-letters treated as separators

use indexmap::IndexMap;
use regex::{Regex, RegexBuilder};

/// One piece of resolved output, in order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Item {
    Text(String),
    Hotkey(String),
}

/// Lowercase, non-letters collapsed to single spaces — used for whole-phrase
/// matching of commands and activation keywords.
pub fn normalize_trigger(text: &str) -> String {
    let lowered: String = text
        .to_lowercase()
        .chars()
        .map(|c| if c.is_ascii_alphabetic() { c } else { ' ' })
        .collect();
    lowered.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Strip surrounding whitespace and sentence punctuation, lowercase.
pub fn normalize_mapping_phrase(text: &str) -> String {
    text.trim()
        .to_lowercase()
        .trim_matches(|c: char| c.is_whitespace() || ".,!?;:".contains(c))
        .to_string()
}

pub struct WordMappings {
    /// Trigger -> replacement, longest trigger first so a longer phrase wins
    /// over a prefix of it.
    rules: Vec<(String, String, Regex)>,
    normalized: IndexMap<String, String>,
}

impl WordMappings {
    pub fn new(mappings: &IndexMap<String, String>) -> Self {
        let mut sorted: Vec<(String, String)> =
            mappings.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        sorted.sort_by_key(|(k, _)| std::cmp::Reverse(k.len()));

        let rules = sorted
            .into_iter()
            .filter_map(|(trigger, replacement)| {
                // \b<trigger>\b plus any trailing punctuation/space
                let pattern = format!(r"\b{}\b[,.\s]*", regex::escape(&trigger));
                RegexBuilder::new(&pattern)
                    .case_insensitive(true)
                    .build()
                    .ok()
                    .map(|re| (trigger, replacement, re))
            })
            .collect();

        let normalized = mappings
            .iter()
            .map(|(k, v)| (normalize_mapping_phrase(k), v.clone()))
            .collect();

        Self { rules, normalized }
    }

    /// Whether the whole utterance is exactly one mapping trigger. Word
    /// mappings only apply in that case, so ordinary dictation containing the
    /// word "proceed" is typed, not turned into a command.
    pub fn is_exact_trigger(&self, text: &str) -> bool {
        self.normalized.contains_key(&normalize_mapping_phrase(text))
    }

    /// Split `text` into literal runs and mapped replacements.
    pub fn apply(&self, text: &str, resolve_clipboard: &dyn Fn() -> String) -> Vec<Item> {
        if self.rules.is_empty() {
            return vec![Item::Text(text.to_string())];
        }

        // Replace each trigger with a marker, remembering what it stood for,
        // then split on the markers. Doing it in one pass per rule keeps the
        // longest-first precedence.
        let mut working = text.to_string();
        let mut replacements: Vec<String> = Vec::new();
        for (_, replacement, re) in &self.rules {
            loop {
                let Some(m) = re.find(&working) else { break };
                let marker = format!("\u{1}{}\u{2}", replacements.len());
                let range = m.range();
                working.replace_range(range, &marker);
                replacements.push(replacement.clone());
            }
        }

        let mut items = Vec::new();
        let mut rest = working.as_str();
        while let Some(start) = rest.find('\u{1}') {
            let (before, after) = rest.split_at(start);
            if !before.trim().is_empty() {
                items.push(Item::Text(before.to_string()));
            }
            let after = &after[1..];
            let Some(end) = after.find('\u{2}') else { break };
            let index: usize = after[..end].parse().unwrap_or(usize::MAX);
            rest = &after[end + 1..];

            if let Some(replacement) = replacements.get(index) {
                items.push(classify(replacement, resolve_clipboard));
            }
        }
        if !rest.trim().is_empty() {
            items.push(Item::Text(rest.to_string()));
        }

        if items.is_empty() {
            vec![Item::Text(text.to_string())]
        } else {
            items
        }
    }
}

/// A short replacement containing `+` is a key combo. Checked before
/// `{{clipboard}}` expansion so pasted text can never be mistaken for one.
fn classify(replacement: &str, resolve_clipboard: &dyn Fn() -> String) -> Item {
    if replacement.contains('+') && replacement.len() < 20 {
        return Item::Hotkey(replacement.to_string());
    }
    Item::Text(resolve_placeholders(replacement, resolve_clipboard))
}

pub fn resolve_placeholders(text: &str, resolve_clipboard: &dyn Fn() -> String) -> String {
    if !text.contains("{{clipboard}}") {
        return text.to_string();
    }
    text.replace("{{clipboard}}", &resolve_clipboard())
}

/// Exact and wildcard phrase -> shell command.
pub struct CommandMappings {
    exact: IndexMap<String, String>,
    /// (prefix, suffix, prefix word count, suffix word count, template)
    wildcard: Vec<(String, String, usize, usize, String)>,
}

impl CommandMappings {
    pub fn new(mappings: &IndexMap<String, String>) -> Self {
        let mut exact = IndexMap::new();
        let mut wildcard = Vec::new();
        for (phrase, command) in mappings {
            match phrase.split_once('*') {
                Some((before, after)) => {
                    let prefix = normalize_trigger(before);
                    let suffix = normalize_trigger(after);
                    let n_prefix = if prefix.is_empty() { 0 } else { prefix.split(' ').count() };
                    let n_suffix = if suffix.is_empty() { 0 } else { suffix.split(' ').count() };
                    wildcard.push((prefix, suffix, n_prefix, n_suffix, command.clone()));
                }
                None => {
                    exact.insert(normalize_trigger(phrase), command.clone());
                }
            }
        }
        Self { exact, wildcard }
    }

    /// The shell command for an utterance, with `$WORDS` substituted.
    pub fn lookup(&self, text: &str) -> Option<String> {
        let norm = normalize_trigger(text);
        if let Some(cmd) = self.exact.get(&norm) {
            return Some(cmd.clone());
        }
        for (prefix, suffix, n_prefix, n_suffix, template) in &self.wildcard {
            let prefix_ok = prefix.is_empty()
                || norm == *prefix
                || norm.starts_with(&format!("{prefix} "));
            let suffix_ok = suffix.is_empty()
                || norm == *suffix
                || norm.ends_with(&format!(" {suffix}"));
            if !(prefix_ok && suffix_ok) {
                continue;
            }
            let words: Vec<&str> = text.split_whitespace().collect();
            let end = words.len().saturating_sub(*n_suffix);
            let captured = words
                .get(*n_prefix..end)
                .map(|w| w.join(" "))
                .unwrap_or_default();
            return Some(template.replace("$WORDS", &captured));
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn no_clipboard() -> String {
        String::new()
    }

    fn map(pairs: &[(&str, &str)]) -> IndexMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn trigger_normalization_treats_non_letters_as_separators() {
        assert_eq!(normalize_trigger("Work  Unlock, Laptop!"), "work unlock laptop");
        assert_eq!(normalize_trigger("home agent 42 shutdown"), "home agent shutdown");
    }

    #[test]
    fn mapping_phrase_normalization_strips_sentence_punctuation() {
        assert_eq!(normalize_mapping_phrase("  New Line. "), "new line");
        assert_eq!(normalize_mapping_phrase("Proceed!"), "proceed");
    }

    #[test]
    fn exact_trigger_detection_gates_word_mappings() {
        let m = WordMappings::new(&map(&[("new line", "\n"), ("proceed", "proceed\n")]));
        assert!(m.is_exact_trigger("New line."));
        assert!(m.is_exact_trigger("proceed"));
        // Ordinary dictation that merely contains a trigger must not count.
        assert!(!m.is_exact_trigger("please proceed with the plan"));
    }

    #[test]
    fn word_mapping_replaces_the_trigger_and_keeps_surrounding_text() {
        let m = WordMappings::new(&map(&[("insert bullet", "- ")]));
        let items = m.apply("insert bullet first point", &no_clipboard);
        assert_eq!(
            items,
            vec![Item::Text("- ".into()), Item::Text("first point".into())]
        );
    }

    #[test]
    fn longest_trigger_wins() {
        let m = WordMappings::new(&map(&[("new", "N"), ("new line", "\n")]));
        let items = m.apply("new line", &no_clipboard);
        assert_eq!(items, vec![Item::Text("\n".into())]);
    }

    #[test]
    fn short_replacement_with_plus_is_a_hotkey() {
        let m = WordMappings::new(&map(&[("now undo", "ctrl+z")]));
        assert_eq!(
            m.apply("now undo", &no_clipboard),
            vec![Item::Hotkey("ctrl+z".into())]
        );
    }

    #[test]
    fn long_replacement_with_plus_is_text_not_a_hotkey() {
        // An email address contains '+' but is obviously not a key combo.
        let m = WordMappings::new(&map(&[("my email", "someone+tag@example.com")]));
        assert_eq!(
            m.apply("my email", &no_clipboard),
            vec![Item::Text("someone+tag@example.com".into())]
        );
    }

    #[test]
    fn clipboard_placeholder_is_resolved() {
        let m = WordMappings::new(&map(&[("insert citation", "- {{clipboard}}:")]));
        let clip = || "https://example.com".to_string();
        assert_eq!(
            m.apply("insert citation", &clip),
            vec![Item::Text("- https://example.com:".into())]
        );
    }

    #[test]
    fn clipboard_content_is_never_treated_as_a_hotkey() {
        // Classification happens before expansion, so clipboard text that
        // looks like a combo still gets typed.
        let m = WordMappings::new(&map(&[("paste it", "{{clipboard}}")]));
        let clip = || "ctrl+z".to_string();
        assert_eq!(
            m.apply("paste it", &clip),
            vec![Item::Text("ctrl+z".into())]
        );
    }

    #[test]
    fn unmapped_text_passes_through_unchanged() {
        let m = WordMappings::new(&map(&[("new line", "\n")]));
        assert_eq!(
            m.apply("hello world", &no_clipboard),
            vec![Item::Text("hello world".into())]
        );
    }

    #[test]
    fn exact_command_phrases_match_after_normalization() {
        let c = CommandMappings::new(&map(&[("work password", "~/wlogin.sh")]));
        assert_eq!(c.lookup("Work password."), Some("~/wlogin.sh".into()));
        assert_eq!(c.lookup("work the password"), None);
    }

    #[test]
    fn wildcard_commands_capture_the_spoken_words() {
        let c = CommandMappings::new(&map(&[("home agent *", "run.sh \"$WORDS\"")]));
        assert_eq!(
            c.lookup("home agent turn off the lights"),
            Some("run.sh \"turn off the lights\"".into())
        );
    }

    #[test]
    fn wildcard_with_a_suffix_captures_the_middle() {
        let c = CommandMappings::new(&map(&[("set * please", "set.sh $WORDS")]));
        assert_eq!(
            c.lookup("set volume to eleven please"),
            Some("set.sh volume to eleven".into())
        );
    }

    #[test]
    fn non_matching_utterance_has_no_command() {
        let c = CommandMappings::new(&map(&[("work password", "x")]));
        assert_eq!(c.lookup("just some dictation"), None);
    }
}

"""Training-only logger changes; release checkpoint gameplay remains untouched."""
MARKER='// Compact training logs v2'


def apply(path):
    text=path.read_text(encoding='utf-8')
    if MARKER in text:return
    replacements={
        'sample = (start_round % 16 == 0) && rows < 768;':
            'sample = (start_round % 64 == 0) && rows < 128;',
        'rows<768':'rows<128',
        'log.text(" "); log.text(action);':
            'log.text(" @"); unsigned action_id=5381; for (unsigned char c:std::string_view{action}) action_id=(action_id*33+c)&65535; log.number(action_id);',
        'if constexpr (learned::telemetry) {\n        const auto position':
            'if constexpr (learned::telemetry) if (sample || shop_spent || failed_actions || me.state().contains(cambc::champion_state::submit_gems_cancelled)) {\n        const auto position',
    }
    for old,new in replacements.items():
        if old not in text: raise ValueError('Unknown logger source; cannot compact safely: '+old)
        text=text.replace(old,new)
    path.write_text(MARKER+'\n'+text,encoding='utf-8')

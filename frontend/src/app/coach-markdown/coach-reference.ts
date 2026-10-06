export type CoachReference =
  | { kind: 'move'; uci: string; label: string }
  | { kind: 'square'; square: string; label: string }
  | { kind: 'line'; moves: string[]; label: string };

const UCI_PATTERN = /^[a-h][1-8][a-h][1-8][qrbn]?$/i;
const SQUARE_PATTERN = /^[a-h][1-8]$/i;

export function parseCoachReference(kind: string, body: string): CoachReference | null {
  if (kind.toLowerCase() === 'move') {
    const attributes = parseAttributes(body, 'uci');
    if (!attributes || !UCI_PATTERN.test(attributes['uci'])) {
      return null;
    }
    const uci = attributes['uci'].toLowerCase();
    return { kind: 'move', uci, label: cleanLabel(attributes['label'], uci) };
  }

  if (kind.toLowerCase() === 'square') {
    const attributes = parseAttributes(body, 'sq');
    if (!attributes || !SQUARE_PATTERN.test(attributes['sq'])) {
      return null;
    }
    const square = attributes['sq'].toLowerCase();
    return { kind: 'square', square, label: cleanLabel(attributes['label'], square) };
  }

  if (kind.toLowerCase() === 'line') {
    const [movesPart, label] = body.split(',label=');
    if (!movesPart?.startsWith('moves=') || label === undefined) {
      return null;
    }
    const moves = movesPart.slice('moves='.length).split(',');
    if (moves.length < 2 || !moves.every((move) => UCI_PATTERN.test(move))) {
      return null;
    }
    return {
      kind: 'line',
      moves: moves.map((move) => move.toLowerCase()),
      label: cleanLabel(label, moves.join(' puis ')),
    };
  }

  return null;
}

function parseAttributes(body: string, required: string): Record<string, string> | null {
  const attributes: Record<string, string> = {};
  for (const item of body.split(',')) {
    const [key, ...valueParts] = item.split('=');
    const value = valueParts.join('=').trim();
    if (!key || !value || ![required, 'label'].includes(key) || attributes[key]) {
      return null;
    }
    attributes[key] = value;
  }
  return attributes[required] ? attributes : null;
}

function cleanLabel(value: string | undefined, fallback: string): string {
  return (value || fallback).replace(/\s+/g, ' ').trim().slice(0, 120) || fallback;
}

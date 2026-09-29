import { Injectable } from '@angular/core';
import type { Dests, Key } from '@lichess-org/chessground/types';
import { Chess } from 'chess.js';

import { BoardMove } from '../models/game';

export interface GameSnapshot {
  fen: string;
  pgn: string;
  moves: string[];
  legalDests: Dests;
  turn: 'white' | 'black';
}

export interface ApplyMoveResult {
  ok: boolean;
  snapshot: GameSnapshot;
}

@Injectable({ providedIn: 'root' })
export class GameStateService {
  private game = new Chess();

  reset(): GameSnapshot {
    this.game = new Chess();
    return this.snapshot();
  }

  applyMove(move: BoardMove): ApplyMoveResult {
    try {
      this.game.move({ from: move.from, to: move.to, promotion: 'q' });
      return { ok: true, snapshot: this.snapshot() };
    } catch {
      return { ok: false, snapshot: this.snapshot() };
    }
  }

  snapshot(): GameSnapshot {
    return {
      fen: this.game.fen(),
      pgn: this.getShortPgn(),
      moves: this.game.history({ verbose: true }).map((move) => move.lan),
      legalDests: this.getLegalDests(),
      turn: this.game.turn() === 'w' ? 'white' : 'black',
    };
  }

  private getLegalDests(): Dests {
    const dests: Dests = new Map();

    for (const move of this.game.moves({ verbose: true })) {
      const from = move.from as Key;
      const to = move.to as Key;
      const targets = dests.get(from) ?? [];

      targets.push(to);
      dests.set(from, targets);
    }

    return dests;
  }

  private getShortPgn(): string {
    return this.game
      .history()
      .reduce<string[]>((parts, move, index) => {
        if (index % 2 === 0) {
          parts.push(`${Math.floor(index / 2) + 1}. ${move}`);
          return parts;
        }

        parts[parts.length - 1] = `${parts[parts.length - 1]} ${move}`;
        return parts;
      }, [])
      .join(' ');
  }
}

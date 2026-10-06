import { Injectable } from '@angular/core';
import type { Dests, Key } from '@lichess-org/chessground/types';
import { Chess } from 'chess.js';

import { BoardMove } from '../models/game';

export interface GameSnapshot {
  fen: string;
  pgn: string;
  moves: string[];
  line: string[];
  legalMoves: string[];
  legalDests: Dests;
  turn: 'white' | 'black';
  currentIndex: number;
  totalMoves: number;
  canGoBack: boolean;
  canGoForward: boolean;
}

export interface ApplyMoveResult {
  ok: boolean;
  snapshot: GameSnapshot;
}

@Injectable({ providedIn: 'root' })
export class GameStateService {
  private game = new Chess();
  private committed: string[] = [];
  private cursor = 0;

  reset(): GameSnapshot {
    this.game = new Chess();
    this.committed = [];
    this.cursor = 0;
    return this.snapshot();
  }

  applyMove(move: BoardMove): ApplyMoveResult {
    try {
      const applied = this.game.move({ from: move.from, to: move.to, promotion: move.promotion ?? 'q' });
      this.committed = [...this.committed.slice(0, this.cursor), applied.lan];
      this.cursor = this.committed.length;
      return { ok: true, snapshot: this.snapshot() };
    } catch {
      return { ok: false, snapshot: this.snapshot() };
    }
  }

  applyLine(moves: BoardMove[]): ApplyMoveResult {
    const applied: string[] = [];
    try {
      for (const move of moves) {
        const next = this.game.move({
          from: move.from,
          to: move.to,
          promotion: move.promotion ?? 'q',
        });
        applied.push(next.lan);
      }
    } catch {
      for (let index = 0; index < applied.length; index++) {
        this.game.undo();
      }
      return { ok: false, snapshot: this.snapshot() };
    }

    this.committed = [...this.committed.slice(0, this.cursor), ...applied];
    this.cursor = this.committed.length;
    return { ok: true, snapshot: this.snapshot() };
  }

  goBack(): GameSnapshot | null {
    if (this.cursor === 0) {
      return null;
    }
    this.game.undo();
    this.cursor--;
    return this.snapshot();
  }

  goForward(): GameSnapshot | null {
    if (this.cursor >= this.committed.length) {
      return null;
    }
    const lan = this.committed[this.cursor];
    try {
      this.game.move({
        from: lan.slice(0, 2),
        to: lan.slice(2, 4),
        promotion: (lan.slice(4, 5) || 'q') as 'q',
      });
    } catch {
      return null;
    }
    this.cursor++;
    return this.snapshot();
  }

  snapshot(): GameSnapshot {
    const moves = this.game.history({ verbose: true }).map((move) => move.lan);

    return {
      fen: this.game.fen(),
      pgn: this.getShortPgn(),
      moves,
      line: [...this.committed],
      legalMoves: this.game.moves({ verbose: true }).map((move) => move.lan),
      legalDests: this.getLegalDests(),
      turn: this.game.turn() === 'w' ? 'white' : 'black',
      currentIndex: this.cursor,
      totalMoves: this.committed.length,
      canGoBack: this.cursor > 0,
      canGoForward: this.cursor < this.committed.length,
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

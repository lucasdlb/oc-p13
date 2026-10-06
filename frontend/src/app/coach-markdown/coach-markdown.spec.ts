import { TestBed } from '@angular/core/testing';

import { CoachMarkdownComponent } from './coach-markdown';
import { RecommendedMove } from '../models/analysis';

const E5: RecommendedMove = {
  uci: 'e7e5',
  san: 'e5',
  description: 'Conteste le centre.',
  source: 'lichess-opening-explorer',
  games: 100,
  white: 0.5,
  draws: 0.1,
  black: 0.4,
  average_rating: 1400,
  move_share: 0.6,
  relevant: true,
  badges: [],
};

describe('CoachMarkdownComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CoachMarkdownComponent],
    }).compileComponents();
  });

  it('renders headings, emphasis and explicit chess references', () => {
    const fixture = TestBed.createComponent(CoachMarkdownComponent);
    fixture.componentRef.setInput(
      'text',
      '## Plan simple\n\nJouez **[[move:uci=e7e5,label=e5]]** pour contester le centre.',
    );
    fixture.componentRef.setInput('moves', [E5]);
    fixture.componentRef.setInput('legalMoves', ['e7e5']);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('h2')?.textContent).toBe('Plan simple');
    expect(element.querySelector('strong')?.textContent).toBe('e5');
    expect(element.querySelector('.coach-move')?.getAttribute('href')).toBe('#chess-e7e5');
  });

  it('does not infer a move from a plain SAN-looking word', () => {
    const fixture = TestBed.createComponent(CoachMarkdownComponent);
    fixture.componentRef.setInput('text', 'La case e5 est importante.');
    fixture.componentRef.setInput('moves', [E5]);
    fixture.componentRef.setInput('legalMoves', ['e7e5']);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.coach-move')).toBeNull();
  });

  it('emits the structured move when a rendered move is clicked', () => {
    const fixture = TestBed.createComponent(CoachMarkdownComponent);
    fixture.componentRef.setInput('text', 'Regardez [[move:uci=e7e5,label=e5]].');
    fixture.componentRef.setInput('moves', [E5]);
    fixture.componentRef.setInput('legalMoves', ['e7e5']);
    fixture.detectChanges();
    const requested = vi.fn();
    fixture.componentInstance.moveRequested.subscribe(requested);

    fixture.nativeElement.querySelector('.coach-move')?.dispatchEvent(
      new MouseEvent('click', { bubbles: true }),
    );

    expect(requested).toHaveBeenCalledWith({ from: 'e7', to: 'e5' });
  });

  it('previews a rendered move on hover and clears it on exit', () => {
    const fixture = TestBed.createComponent(CoachMarkdownComponent);
    fixture.componentRef.setInput('text', 'Regardez [[move:uci=e7e5,label=e5]].');
    fixture.componentRef.setInput('moves', [E5]);
    fixture.componentRef.setInput('legalMoves', ['e7e5']);
    fixture.detectChanges();
    const previewed = vi.fn();
    fixture.componentInstance.movePreview.subscribe(previewed);
    const link = fixture.nativeElement.querySelector('.coach-move') as HTMLAnchorElement;

    link.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    expect(previewed).toHaveBeenLastCalledWith({ from: 'e7', to: 'e5' });

    link.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }));
    expect(previewed).toHaveBeenLastCalledWith(null);
  });

  it('renders a square reference without making it a move', () => {
    const fixture = TestBed.createComponent(CoachMarkdownComponent);
    fixture.componentRef.setInput('text', 'Visez [[square:sq=e5,label=e5]].');
    fixture.detectChanges();
    const requested = vi.fn();
    const squarePreview = vi.fn();
    fixture.componentInstance.moveRequested.subscribe(requested);
    fixture.componentInstance.squarePreview.subscribe(squarePreview);
    const link = fixture.nativeElement.querySelector('.coach-square-reference') as HTMLAnchorElement;

    link.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    link.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(requested).not.toHaveBeenCalled();
    expect(squarePreview).toHaveBeenLastCalledWith('e5');
  });

  it('renders a legal line as a separate interaction', () => {
    const fixture = TestBed.createComponent(CoachMarkdownComponent);
    fixture.componentRef.setInput('fen', 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1');
    fixture.componentRef.setInput('legalMoves', ['e7e5']);
    fixture.componentRef.setInput('text', 'Suite [[line:moves=e7e5,g1f3,g8f6,label=e5 puis Nf3 puis ...Nf6]].');
    fixture.detectChanges();
    const requested = vi.fn();
    fixture.componentInstance.lineRequested.subscribe(requested);

    (fixture.nativeElement.querySelector('.coach-line') as HTMLAnchorElement).click();

    expect(requested).toHaveBeenCalledWith([
      { from: 'e7', to: 'e5' },
      { from: 'g1', to: 'f3' },
      { from: 'g8', to: 'f6' },
    ]);
  });

  it('disables a move that belongs to the other side to move', () => {
    const fixture = TestBed.createComponent(CoachMarkdownComponent);
    fixture.componentRef.setInput('text', '[[move:uci=e2e4,label=e4]]');
    fixture.componentRef.setInput('legalMoves', ['e7e5']);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.coach-move')).toBeNull();
    expect(fixture.nativeElement.querySelector('.coach-move-disabled')?.textContent).toBe('e4');
  });

  it('does not render raw HTML from coach output', () => {
    const fixture = TestBed.createComponent(CoachMarkdownComponent);
    fixture.componentRef.setInput('text', '<img src=x onerror="alert(1)">\n\n**sain**');
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('img')).toBeNull();
    expect(element.querySelector('strong')?.textContent).toBe('sain');
  });
});

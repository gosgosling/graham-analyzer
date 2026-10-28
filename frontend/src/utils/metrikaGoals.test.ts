import { GOALS, routeGoals } from './metrikaGoals';

describe('routeGoals', () => {
  it('карточка компании — при входе на неё, не при смене вкладки в адресе', () => {
    expect(routeGoals('/company/21', '/companies')).toEqual([GOALS.company]);
    expect(routeGoals('/company/21?tab=reports', '/company/21')).toEqual([]);
    expect(routeGoals('/company/21/reports-matrix', null)).toEqual([]);
  });

  it('отбор в скринере — только смена условий на той же странице', () => {
    expect(routeGoals('/screen', '/')).toEqual([]);
    expect(routeGoals('/screen?sector=oil', '/screen')).toEqual([GOALS.screen]);
    expect(routeGoals('/screen?sector=oil', '/screen?sector=oil')).toEqual([]);
  });

  it('сравнение — от двух компаний или «компания и соседи»', () => {
    expect(routeGoals('/compare?ids=171', '/compare')).toEqual([]);
    expect(routeGoals('/compare?ids=171,44', '/compare?ids=171')).toEqual([GOALS.compare]);
    expect(routeGoals('/compare?with=21', '/company/21')).toEqual([GOALS.compare]);
  });
});

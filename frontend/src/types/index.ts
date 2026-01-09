export interface Security {
    secid: string;
    boardid: string;
    shortname: string;
    prevprice: number | null;
    lotsize: number;
    facevalue: number;
    status: string;
    boardname: string;
    decimals: number;
    secname: string;
    remarks: string | null;
    marketcode: string;
    instrid: string;    
    sectorid: string | null;
    minstep: number;
    prevwaprice: number | null;
    faceunit: string;
    prevdate: string | null; 
    issuesize: number;
    isin: string;
    latname: string;
    regnumber: string | null;
    prevlegalcloseprice: number | null;
    currencyid: string;
    sectype: string;
    listlevel: number;
    settledate: string | null;  
}

export interface Multipliers {
    company_id: number;
    pe_ratio: number;
    pb_ratio: number;
    debt_to_equity: number;
    roe: number;
    dividend_yield: number;
    date: string;
}

export interface Company {
    figi: string;
    ticker: string;
    name: string;
    isin?: string;
    sector?: string;
    currency: string;
    lot: number;
    api_trade_available_flag: boolean;
}
/**
 * ZY 数据域 schema 主入口
 * 聚合 9 个域的元数据并提供查询/工具函数
 */
import K from './keys';
import asset from './01_asset';
import subject from './02_subject';
import product from './03_product';
import valuation from './04_valuation';
import transaction from './05_transaction';
import seller from './06_seller';
import customer from './07_customer';
import risk from './08_risk';
import market from './09_market';

export const DOMAINS = [
  asset, subject, product, valuation, transaction,
  seller, customer, risk, market
];

export const KEYS = K;
export const BIZ_DT = K.BIZ_DT;
export const AUDIT_FIELDS = K.AUDIT_FIELDS;

/** 根据 domain code/name 查找域 */
export function findDomain(code) {
  return DOMAINS.find(d => d.domain === code || d.domainCode === code);
}

/** 根据 collection 名称查找表 schema（含 domain 引用） */
export function findTable(collection) {
  for (const d of DOMAINS) {
    const t = d.tables.find(x => x.name === collection);
    if (t) return { domain: d, table: t };
  }
  return null;
}

/** 全表清单（扁平），用于全局检索 */
export function flatTables() {
  const arr = [];
  DOMAINS.forEach(d => {
    d.tables.forEach(t => {
      arr.push({
        domain: d.domain,
        domainName: d.domainName,
        domainCode: d.domainCode,
        name: t.name,
        label: t.label,
        pk: t.pk,
        fieldCount: t.fields.length
      });
    });
  });
  return arr;
}

/** 数据域汇总信息（用于左侧树/卡片展示） */
export function domainSummary() {
  return DOMAINS.map(d => ({
    domain: d.domain,
    domainName: d.domainName,
    domainCode: d.domainCode,
    icon: d.icon,
    color: d.color,
    tableCount: d.tables.length
  }));
}

export default {
  DOMAINS,
  KEYS,
  BIZ_DT,
  AUDIT_FIELDS,
  findDomain,
  findTable,
  flatTables,
  domainSummary
};

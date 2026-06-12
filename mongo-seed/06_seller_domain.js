load('_keys.js');
/**
 * 销售域 dwd_seller_info — 1 张表 (6条)
 * 主键：SELLER_ID
 */
print('--- [06] seller domain start ---');

var BIZ_DT = ZY_KEYS.BIZ_DT;
var aud    = ZY_KEYS.audit;

/* ================ 1. dwd_seller_info 销售人员信息 (6条) ================ */
var col = ZY_KEYS.recreate('dwd_seller_info');
col.createIndex({ SELLER_ID: 1 }, { unique: true });
col.createIndex({ REGION: 1, RANK: 1 });

var sellerSeed = [
  { SELLER_ID: 'SEL00001', SELLER_NM: '刘洋', DEPT: '机构销售一部', TITLE: '高级客户经理', PHONE: '13800138001', EMAIL: 'liuyang@company.com', ENTRY_DT: '20180315', CUSTOMER_CNT: 12, AUM_TOTAL: 3500000000, YTD_SALES: 800000000, RANK: 'SENIOR', STATUS: 'ACTIVE', REGION: '华东' },
  { SELLER_ID: 'SEL00002', SELLER_NM: '赵丽华', DEPT: '机构销售一部', TITLE: '客户经理', PHONE: '13800138002', EMAIL: 'zhaolh@company.com', ENTRY_DT: '20200610', CUSTOMER_CNT: 8, AUM_TOTAL: 1800000000, YTD_SALES: 450000000, RANK: 'SENIOR', STATUS: 'ACTIVE', REGION: '华北' },
  { SELLER_ID: 'SEL00003', SELLER_NM: '孙志强', DEPT: '机构销售二部', TITLE: '销售总监', PHONE: '13800138003', EMAIL: 'sunzq@company.com', ENTRY_DT: '20150708', CUSTOMER_CNT: 18, AUM_TOTAL: 5200000000, YTD_SALES: 1200000000, RANK: 'DIRECTOR', STATUS: 'ACTIVE', REGION: '华东' },
  { SELLER_ID: 'SEL00004', SELLER_NM: '周敏', DEPT: '零售销售部', TITLE: '客户经理', PHONE: '13800138004', EMAIL: 'zhoumin@company.com', ENTRY_DT: '20210420', CUSTOMER_CNT: 25, AUM_TOTAL: 800000000, YTD_SALES: 200000000, RANK: 'JUNIOR', STATUS: 'ACTIVE', REGION: '华南' },
  { SELLER_ID: 'SEL00005', SELLER_NM: '吴晓峰', DEPT: '机构销售二部', TITLE: '高级客户经理', PHONE: '13800138005', EMAIL: 'wuxf@company.com', ENTRY_DT: '20170901', CUSTOMER_CNT: 15, AUM_TOTAL: 4200000000, YTD_SALES: 950000000, RANK: 'SENIOR', STATUS: 'ACTIVE', REGION: '华北' },
  { SELLER_ID: 'SEL00006', SELLER_NM: '郑雯', DEPT: '零售销售部', TITLE: '初级客户经理', PHONE: '13800138006', EMAIL: 'zhengwen@company.com', ENTRY_DT: '20230815', CUSTOMER_CNT: 6, AUM_TOTAL: 350000000, YTD_SALES: 80000000, RANK: 'JUNIOR', STATUS: 'ACTIVE', REGION: '华南' }
];
sellerSeed.forEach(function (d) { d.BIZ_DT = BIZ_DT; Object.assign(d, aud()); });
col.insertMany(sellerSeed);
print('  dwd_seller_info: ' + col.countDocuments());

print('--- [06] seller domain done ---');

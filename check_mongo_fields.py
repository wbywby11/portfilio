from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017')
db = client['portfilio']

collections_to_check = [
    'dwd_ast_info',
    'dwd_mkt_stock', 
    'dwd_cust_trade',
    'dwd_ptl_nav'
]

for coll_name in collections_to_check:
    coll = db[coll_name]
    doc = coll.find_one()
    
    if doc:
        print(coll_name + ':')
        print('-' * 60)
        print('Fields in database: ' + str(len(doc)) + ' total')
        print('Fields: ' + str(sorted(list(doc.keys()))))
        
        null_count = sum(1 for v in doc.values() if v is None)
        empty_count = sum(1 for v in doc.values() if v == '')
        print('Null values: ' + str(null_count) + ', Empty strings: ' + str(empty_count))

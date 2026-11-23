REASONS={"BAD_COLUMNS":"列数不匹配","EMPTY_VALUE":"必填值为空","INVALID_NUMBER":"数字格式错误","INVALID_TIME":"时间缺少偏移或格式错误","DUPLICATE_CONFLICT":"同键取值冲突","UNKNOWN_REFERENCE":"引用不存在","STALE_VERSION":"版本已更新","EMPTY_FILE":"文件为空","HEADER_ONLY":"仅有表头","BLANK_ONLY":"全部为空行","QUOTA_EXCEEDED":"超出本次放行额度","INDEX_AHEAD":"索引版本超前，需人工核对","NEEDS_REVIEW":"状态需人工核对","RELEASE_IMPERSONATION":"未入选文档冒充已同步","RELEASE_UNBALANCED":"放行单未覆盖全部积压","BAD_QUOTA":"放行额度需为非负整数"}
def reject(row, code, detail):
    return {**row,"reason":code,"detail":detail}
def sources(row):
    return row.get("_sources", [row.get("_line",0)])

class PermissionConstant:
    """
    权限常量类 - 按业务模块分组管理所有系统权限

    该类定义了系统中各个业务模块的权限标识符，采用分层结构组织：
    - 每个业务域作为一个内部类（如 Sales, Purchase, Inventory 等）
    - 每个权限使用 "资源:操作" 格式定义
    - 支持 CRUD 操作及业务特定操作（如 approve, export 等）

    使用示例:
        >>> Permission.Sales.ORDER_CREATE  # 获取销售订单创建权限
        'sales_order:create'
        >>> Permission.get_all()  # 获取所有权限列表
        ['sales_order:create', 'sales_order:read', ...]
    """

    class Sales:
        """
        销售域权限常量

        包含销售相关的权限定义：
        - 销售订单管理（ORDER_*）
        - 销售出库管理（OUTBOUND_*）
        - 客户管理（CUSTOMER_*）

        权限格式: sales_order:create, customer:export 等
        """

        ORDER_CREATE = "sales_order:create"  # 创建销售订单
        ORDER_READ = "sales_order:read"  # 读取销售订单
        ORDER_UPDATE = "sales_order:update"  # 修改销售订单
        ORDER_DELETE = "sales_order:delete"  # 删除销售订单

        OUTBOUND_CREATE = "sales_outbound:create"  # 创建销售出库
        OUTBOUND_READ = "sales_outbound:read"  # 读取销售出库
        OUTBOUND_UPDATE = "sales_outbound:update"  # 修改销售出库
        OUTBOUND_DELETE = "sales_outbound:delete"  # 删除销售出库
        OUTBOUND_APPROVE = "sales_outbound:approve"  # 审批销售出库

        CUSTOMER_CREATE = "customer:create"  # 创建客户
        CUSTOMER_READ = "customer:read"  # 读取客户
        CUSTOMER_UPDATE = "customer:update"  # 修改客户
        CUSTOMER_DELETE = "customer:delete"  # 删除客户
        CUSTOMER_EXPORT = "customer:export"  # 导出客户

    class Purchase:
        """
        采购域权限常量

        包含采购相关的权限定义：
        - 采购订单管理（ORDER_*）
        - 采购入库管理（INBOUND_*），包含审批和取消操作
        - 供应商管理（SUPPLIER_*）

        权限格式: purchase_order:create, supplier:update 等
        """

        ORDER_CREATE = "purchase_order:create"  # 创建采购订单
        ORDER_READ = "purchase_order:read"  # 读取采购订单
        ORDER_UPDATE = "purchase_order:update"  # 更新采购订单
        ORDER_DELETE = "purchase_order:delete"  # 删除采购订单

        INBOUND_CREATE = "purchase_inbound:create"  # 创建采购入库
        INBOUND_READ = "purchase_inbound:read"  # 读取采购入库
        INBOUND_UPDATE = "purchase_inbound:update"  # 更新采购入库
        INBOUND_DELETE = "purchase_inbound:delete"  # 删除采购入库
        INBOUND_APPROVE = "purchase_inbound:approve"  # 审批采购入库
        INBOUND_CANCEL = "purchase_inbound:cancel"  # 取消采购入库

        SUPPLIER_CREATE = "supplier:create"  # 创建供应商
        SUPPLIER_READ = "supplier:read"  # 读取供应商
        SUPPLIER_UPDATE = "supplier:update"  # 更新供应商
        SUPPLIER_DELETE = "supplier:delete"  # 删除供应商

    class Inventory:
        """
        库存域权限常量

        包含库存管理相关的权限定义：
        - 库存管理（STOCK_*）
        - 仓库管理（WAREHOUSE_*）
        - 其他出入库单据（OTHER_INBOUND_*, OTHER_OUTBOUND_*）
        - 调拨单管理（TRANSFER_*）
        - 盘点单管理（STOCK_CHECK_*）

        特点: 大部分单据支持审批流程（APPROVE 权限）
        权限格式: stock:read, transfer:approve 等
        """

        STOCK_CREATE = "stock:create"  # 创建库存
        STOCK_READ = "stock:read"  # 读取库存
        STOCK_UPDATE = "stock:update"  # 更新库存
        STOCK_DELETE = "stock:delete"  # 删除库存

        WAREHOUSE_CREATE = "warehouse:create"  # 创建仓库
        WAREHOUSE_READ = "warehouse:read"  # 读取仓库
        WAREHOUSE_UPDATE = "warehouse:update"  # 更新仓库
        WAREHOUSE_DELETE = "warehouse:delete"  # 删除仓库

        # 库存单据

        OTHER_INBOUND_CREATE = "other_inbound:create"  # 创建其他入库
        OTHER_INBOUND_READ = "other_inbound:read"  # 读取其他入库
        OTHER_INBOUND_UPDATE = "other_inbound:update"  # 更新其他入库
        OTHER_INBOUND_DELETE = "other_inbound:delete"  # 删除其他入库
        OTHER_INBOUND_APPROVE = "other_inbound:approve"  # 审核其他入库

        OTHER_OUTBOUND_CREATE = "other_outbound:create"  # 创建其他出库
        OTHER_OUTBOUND_READ = "other_outbound:read"  # 读取其他出库
        OTHER_OUTBOUND_UPDATE = "other_outbound:update"  # 更新其他出库
        OTHER_OUTBOUND_DELETE = "other_outbound:delete"  # 删除其他出库
        OTHER_OUTBOUND_APPROVE = "other_outbound:approve"  # 审核其他出库

        TRANSFER_CREATE = "transfer:create"  # 创建调拨
        TRANSFER_READ = "transfer:read"  # 读取调拨
        TRANSFER_UPDATE = "transfer:update"  # 更新调拨
        TRANSFER_DELETE = "transfer:delete"  # 删除调拨
        TRANSFER_APPROVE = "transfer:approve"  # 审核调拨

        STOCK_CHECK_CREATE = "stock_check:create"  # 创建盘点
        STOCK_CHECK_READ = "stock_check:read"  # 读取盘点
        STOCK_CHECK_UPDATE = "stock_check:update"  # 更新盘点
        STOCK_CHECK_DELETE = "stock_check:delete"  # 删除盘点
        STOCK_CHECK_APPROVE = "stock_check:approve"  # 审核盘点

    class Product:
        """
        产品主数据权限常量

        包含产品和基础数据管理的权限定义：
        - 产品管理（PRODUCT_*），支持导入导出
        - 产品分类管理（CATEGORY_*）
        - 计量单位管理（UNIT_*）

        权限格式: product:import, product_category:read 等
        """

        PRODUCT_CREATE = "product:create"  # 创建产品
        PRODUCT_READ = "product:read"  # 读取产品
        PRODUCT_UPDATE = "product:update"  # 更新产品
        PRODUCT_DELETE = "product:delete"  # 删除产品
        PRODUCT_IMPORT = "product:import"  # 导入产品
        PRODUCT_EXPORT = "product:export"  # 导出产品

        CATEGORY_CREATE = "product_category:create"  # 创建产品分类
        CATEGORY_READ = "product_category:read"  # 读取产品分类
        CATEGORY_UPDATE = "product_category:update"  # 更新产品分类
        CATEGORY_DELETE = "product_category:delete"  # 删除产品分类

        UNIT_CREATE = "unit:create"  # 创建单位
        UNIT_READ = "unit:read"  # 读取单位
        UNIT_UPDATE = "unit:update"  # 更新单位
        UNIT_DELETE = "unit:delete"  # 删除单位

    class Finance:
        """
        财务域权限常量

        包含财务管理相关的权限定义：
        - 应收应付查询（RECEIVABLE_READ, PAYABLE_READ）
        - 付款管理（PAYMENT_*），包含审批流程
        - 发票管理（INVOICE_*）

        注意: 财务域以只读权限为主，写操作需要审批
        权限格式: payment:approve, invoice:create 等
        """

        RECEIVABLE_READ = "receivable:read"  # 读取应收应付
        PAYABLE_READ = "payable:read"  # 读取应付
        PAYMENT_CREATE = "payment:create"  # 创建付款
        PAYMENT_READ = "payment:read"  # 读取付款
        PAYMENT_APPROVE = "payment:approve"  # 审批付款
        INVOICE_CREATE = "invoice:create"  # 创建发票
        INVOICE_READ = "invoice:read"  # 读取发票

    class Report:
        """
        报表与分析权限常量

        包含各类报表查看权限：
        - 销售报表（SALES_VIEW）
        - 采购报表（PURCHASE_VIEW）
        - 库存报表（STOCK_VIEW）
        - 财务报表（FINANCE_VIEW）
        - 仪表盘（DASHBOARD_VIEW）

        特点: 所有权限均为只读查看权限
        权限格式: report:sales:view, dashboard:view 等
        """

        SALES_VIEW = "report_sales:view"  # 销售报表
        PURCHASE_VIEW = "report_purchase:view"  # 采购报表
        STOCK_VIEW = "report_stock:view"  # 库存报表
        FINANCE_VIEW = "report_finance:view"  # 财务报表
        DASHBOARD_VIEW = "dashboard:view"  # 仪表盘

    class System:
        """
        系统管理权限常量

        包含系统级管理功能的权限定义：
        - 人员管理（PERSONNEL_*）
        - 角色管理（ROLE_*），包含角色分配权限
        - 系统配置（CONFIG_*）
        - 审计日志（AUDIT_LOG_READ）
        - 数据备份恢复（BACKUP_*）

        注意: 这些是最高权限级别的操作，应谨慎分配
        权限格式: role:assign, backup:restore 等
        """

        PERSONNEL_CREATE = "personnel:create"  # 创建人员
        PERSONNEL_READ = "personnel:read"  # 读取人员
        PERSONNEL_UPDATE = "personnel:update"  # 更新人员
        PERSONNEL_DELETE = "personnel:delete"  # 删除人员

        ROLE_CREATE = "role:create"  # 创建角色
        ROLE_READ = "role:read"  # 读取角色
        ROLE_UPDATE = "role:update"  # 更新角色
        ROLE_DELETE = "role:delete"  # 删除角色
        ASSIGN_PERMISSION = "permission:assign"  #  分配权限
        ASSIGN_ROLE = "role:assign"  # 分配角色

        CONFIG_READ = "system_config:read"  # 读取系统配置
        CONFIG_UPDATE = "system_config:update"  # 更新系统配置
        AUDIT_LOG_READ = "audit_log:read"  # 读取审计日志
        BACKUP_CREATE = "backup:create"  # 创建备份
        BACKUP_RESTORE = "backup:restore"  # 恢复备份

    @classmethod
    def get_all(cls):
        """
        获取系统中定义的所有权限字符串列表

        该方法通过反射机制自动收集所有内部类中定义的权限常量，
        用于数据库同步、权限初始化等场景。

        工作流程:
        1. 遍历 Permission 类的所有属性
        2. 跳过私有属性和非类属性
        3. 对每个内部类，遍历其所有字符串类型的权限常量
        4. 过滤出符合 "resource:action" 格式的权限标识

        Returns:
            list[str]: 所有权限字符串的列表，例如:
                [
                    'sales_order:create',
                    'sales_order:read',
                    'customer:export',
                    ...
                ]

        使用示例:
            >>> all_perms = Permission.get_all()
            >>> len(all_perms)  # 获取权限总数
            85
            >>> 'sales_order:create' in all_perms  # 检查权限是否存在
            True

        Note:
            - 该方法会自动排除以下划线开头的私有属性
            - 只收集包含冒号的字符串值，确保是有效的权限标识
            - 返回的列表顺序取决于 dir() 函数的返回顺序
        """
        perms = []
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if attr_name.startswith("_") or not hasattr(attr, "__dict__"):
                continue
            # 遍历内部类的属性
            for sub_attr in dir(attr):
                if sub_attr.startswith("_"):
                    continue
                val = getattr(attr, sub_attr)
                if isinstance(val, str) and ":" in val:
                    perms.append(val)
        return perms

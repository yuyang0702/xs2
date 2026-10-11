#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeterminFlow 插件自动检测和安装脚本
在首次部署或插件缺失时自动安装必需的插件
"""

import json
import shutil
import sys
import codecs
from pathlib import Path
from typing import List, Dict, Any

# 设置标准输出编码为 UTF-8
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')


class PluginManager:
    """管理 DeterminFlow 插件的自动化安装"""

    # 必需的默认插件列表
    REQUIRED_PLUGINS = {
        "xs2-novel-flywheel": {
            "name": "XS2 Novel Flywheel",
            "description": "Novel production workflows with selectable reference learning",
            "repository": "parent",  # 从父目录 DeterminFlow-Plugins 复制
        }
    }

    def __init__(self):
        """初始化插件管理器"""
        self.determinflow_root = Path(__file__).parent
        self.plugins_dir = self.determinflow_root / "data" / "plugins"
        self.source_dir = self.determinflow_root.parent / "DeterminFlow-Plugins" / "plugins"
        self.plugins_config_file = self.determinflow_root / "plugins_installed.json"

    def _ensure_plugins_dir(self):
        """确保插件目录存在"""
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    def _get_installed_plugins(self) -> Dict[str, Any]:
        """读取已安装的插件列表"""
        if self.plugins_config_file.exists():
            try:
                with open(self.plugins_config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_installed_plugins(self, plugins: Dict[str, Any]):
        """保存已安装的插件列表"""
        with open(self.plugins_config_file, "w", encoding="utf-8") as f:
            json.dump(plugins, f, indent=2, ensure_ascii=False)

    def _plugin_exists(self, plugin_id: str) -> bool:
        """检查插件是否已安装"""
        plugin_source = self.source_dir / plugin_id if plugin_id != "built-in" else None

        if plugin_source and plugin_source.exists():
            return True

        # 检查是否在已安装列表中
        installed = self._get_installed_plugins()
        return plugin_id in installed and installed[plugin_id].get("installed", False)

    def _install_plugin(self, plugin_id: str, plugin_config: Dict[str, Any]) -> bool:
        """安装单个插件"""
        print(f"\n📦 安装插件: {plugin_config.get('name', plugin_id)}")

        source_path = self.source_dir / plugin_id
        if not source_path.exists():
            print(f"  ✗ 插件源未找到: {source_path}")
            return False

        # 这里不需要复制，DeterminFlow 会从源目录加载
        # 只需要在配置中记录
        print(f"  ✓ 插件已就绪: {source_path}")

        # 更新已安装插件配置
        installed = self._get_installed_plugins()
        installed[plugin_id] = {
            "name": plugin_config.get("name"),
            "installed": True,
            "version": "auto-detected",
            "auto_install": True,
        }
        self._save_installed_plugins(installed)

        return True

    def check_and_install_required_plugins(self) -> bool:
        """检查并安装所有必需的插件"""
        print("=" * 60)
        print("DeterminFlow 插件自动检测和安装")
        print("=" * 60)

        self._ensure_plugins_dir()

        missing_plugins = []
        installed_count = 0

        for plugin_id, plugin_config in self.REQUIRED_PLUGINS.items():
            if self._plugin_exists(plugin_id):
                print(f"✓ 插件已安装: {plugin_config.get('name', plugin_id)}")
                installed_count += 1
            else:
                print(f"✗ 插件缺失: {plugin_config.get('name', plugin_id)}")
                missing_plugins.append((plugin_id, plugin_config))

        # 安装缺失的插件
        if missing_plugins:
            print(f"\n检测到 {len(missing_plugins)} 个缺失的插件，正在安装...")

            for plugin_id, plugin_config in missing_plugins:
                if self._install_plugin(plugin_id, plugin_config):
                    installed_count += 1
                else:
                    print(f"  ⚠️  插件安装失败: {plugin_id}")

        print("\n" + "=" * 60)
        print(f"✓ 插件检测完成: {installed_count}/{len(self.REQUIRED_PLUGINS)} 个必需插件已就绪")
        print("=" * 60)

        return installed_count == len(self.REQUIRED_PLUGINS)

    def list_available_plugins(self) -> List[str]:
        """列出所有可用的插件"""
        if not self.source_dir.exists():
            return []

        plugins = []
        for plugin_path in self.source_dir.iterdir():
            if plugin_path.is_dir() and (plugin_path / "extension.toml").exists():
                plugins.append(plugin_path.name)

        return plugins

    def print_plugin_info(self):
        """打印插件信息"""
        print("\n" + "=" * 60)
        print("插件源信息")
        print("=" * 60)

        print(f"源目录: {self.source_dir}")
        print(f"配置文件: {self.plugins_config_file}")

        available_plugins = self.list_available_plugins()
        if available_plugins:
            print(f"\n可用的插件 ({len(available_plugins)}):")
            for plugin in available_plugins:
                status = "✓" if self._plugin_exists(plugin) else "✗"
                print(f"  {status} {plugin}")
        else:
            print("\n⚠️  未找到任何插件源")

        print("\n" + "=" * 60)


def main():
    """主函数"""
    manager = PluginManager()

    # 打印插件信息
    manager.print_plugin_info()

    # 检查并安装必需的插件
    success = manager.check_and_install_required_plugins()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

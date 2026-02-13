"""Signals to adjust Part stock when invoice items are created, updated, or deleted."""

from django.db.models import F
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from catalog.models import Part

from .models import InvoiceItem


def _decrement_part_stock(part_id: int, quantity: int) -> None:
    """Decrement part stock by quantity (atomic)."""
    if part_id and quantity > 0:
        Part.objects.filter(pk=part_id).update(
            stock_quantity=F("stock_quantity") - quantity
        )


def _increment_part_stock(part_id: int, quantity: int) -> None:
    """Increment part stock by quantity (atomic)."""
    if part_id and quantity > 0:
        Part.objects.filter(pk=part_id).update(
            stock_quantity=F("stock_quantity") + quantity
        )


@receiver(pre_save, sender=InvoiceItem)
def store_old_values_for_update(sender, instance, **kwargs):
    """Store old quantity and part_id before save so post_save can compute delta."""
    if instance.pk:
        try:
            old = InvoiceItem.objects.get(pk=instance.pk)
            instance._pre_save_quantity = old.quantity
            instance._pre_save_part_id = old.part_id
        except InvoiceItem.DoesNotExist:
            instance._pre_save_quantity = 0
            instance._pre_save_part_id = None
    else:
        instance._pre_save_quantity = 0
        instance._pre_save_part_id = None


@receiver(pre_delete, sender=InvoiceItem)
def replenish_stock_on_item_delete(sender, instance, **kwargs):
    """When an invoice item is deleted, add its quantity back to part stock."""
    if instance.part_id:
        _increment_part_stock(instance.part_id, instance.quantity)


@receiver(post_save, sender=InvoiceItem)
def adjust_stock_on_item_save(sender, instance, created, **kwargs):
    """When an invoice item is saved, adjust part stock."""
    if not instance.part_id:
        return

    if created:
        _decrement_part_stock(instance.part_id, instance.quantity)
    else:
        old_qty = getattr(instance, "_pre_save_quantity", None)
        old_part_id = getattr(instance, "_pre_save_part_id", None)
        if old_qty is not None:
            delta = instance.quantity - old_qty
            if old_part_id == instance.part_id:
                if delta > 0:
                    _decrement_part_stock(instance.part_id, delta)
                elif delta < 0:
                    _increment_part_stock(instance.part_id, -delta)
            else:
                if old_part_id:
                    _increment_part_stock(old_part_id, old_qty)
                _decrement_part_stock(instance.part_id, instance.quantity)
